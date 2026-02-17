import ankidmpy.util as util
import fnmatch
import glob
import hashlib
import os
import re
import shutil

DEFAULT_ANKIDM_CONFIG = 'ankidm.yaml'
DEFAULT_GUID_MAP_FILE = 'guid-map.yaml'
DEFAULT_CRAWL_INCLUDE = ['**/data.yaml']
TAG_SANITIZE_RE = re.compile(r'[^0-9A-Za-z:_-]+')


def _normalizeStringList(value, key_name):
    if value is None:
        return []

    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        util.err("Invalid '%s': expected string or list of strings." %
                 (key_name,))

    normalized = []
    for idx, item in enumerate(items):
        if not isinstance(item, str) or not item.strip():
            util.err("Invalid '%s' value at index %d: %s" %
                     (key_name, idx, item))
        normalized.append(item.strip())
    return normalized


def _normalizeLevelDefinitions(data):
    levels = data.get('levels')

    if not isinstance(levels, list) or not levels:
        util.err("Path tags config must contain a non-empty 'levels' list.")

    normalized = []
    known_names = set()
    for i, level in enumerate(levels):
        if not isinstance(level, dict):
            util.err("Invalid level at index %d: expected object." % (i,))

        name = level.get('name')
        if not isinstance(name, str) or not name.strip():
            util.err("Invalid level name at index %d: %s" % (i, name))
        name = name.strip()
        if name in known_names:
            util.err("Duplicate level name in path tags config: %s" % (name,))
        known_names.add(name)

        index = level.get('index')
        if not isinstance(index, int) or index < 0:
            util.err("Invalid level index for '%s': %s" % (name, index))

        tag_name = level.get('tag_name')
        if tag_name is None:
            tag_name = level.get('tag')
        if tag_name is not None:
            if not isinstance(tag_name, str):
                util.err("Invalid tag_name for level '%s': %s" %
                         (name, tag_name))
            tag_name = tag_name.strip() or None

        emit_value_tag = level.get('emit_value_tag')
        if emit_value_tag is None:
            emit_value_tag = not bool(tag_name)
        if not isinstance(emit_value_tag, bool):
            util.err("Invalid emit_value_tag for level '%s': %s" %
                     (name, emit_value_tag))

        value_tag_prefix = level.get('value_tag_prefix')
        if value_tag_prefix is not None:
            if not isinstance(value_tag_prefix, str):
                util.err("Invalid value_tag_prefix for level '%s': %s" %
                         (name, value_tag_prefix))
            value_tag_prefix = value_tag_prefix.strip() or None

        value_template = level.get('value_template')
        if value_template is None:
            value_template = '{value}'
        if not isinstance(value_template, str) or not value_template:
            util.err("Invalid value_template for level '%s': %s" %
                     (name, value_template))

        normalized.append({
            'name': name,
            'index': index,
            'emit_value_tag': emit_value_tag,
            'value_tag_prefix': value_tag_prefix,
            'tag_name': tag_name,
            'value_template': value_template
        })

    return normalized


def _normalizePathTagsConfig(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        util.err("Invalid 'path_tags': expected object.")

    config = dict()
    config['levels'] = _normalizeLevelDefinitions(raw)
    config['include_other_segments'] = raw.get('include_other_segments', True)
    if not isinstance(config['include_other_segments'], bool):
        util.err("Invalid 'path_tags.include_other_segments': %s" %
                 (config['include_other_segments'],))
    return config


def _loadAnkiDmConfig(src_dir):
    config_path = os.path.join(src_dir, DEFAULT_ANKIDM_CONFIG)
    raw = util.getYaml(config_path, required=False)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        util.err("File '%s' must contain a top-level object." % (config_path,))

    crawl = raw.get('crawl') or {}
    if not isinstance(crawl, dict):
        util.err("Invalid 'crawl' section in '%s'." % (config_path,))

    crawl_root = crawl.get('root') or '.'
    if not isinstance(crawl_root, str) or not crawl_root.strip():
        util.err("Invalid 'crawl.root' in '%s': %s" % (config_path, crawl_root))

    crawl_root = crawl_root.strip()
    if not os.path.isabs(crawl_root):
        crawl_root = os.path.join(src_dir, crawl_root)
    crawl_root = os.path.abspath(crawl_root)
    if not os.path.isdir(crawl_root):
        util.err("crawl.root directory does not exist: %s" % (crawl_root,))

    include = _normalizeStringList(crawl.get('include'), 'crawl.include')
    if not include:
        include = list(DEFAULT_CRAWL_INCLUDE)
    exclude = _normalizeStringList(crawl.get('exclude'), 'crawl.exclude')

    path_tags = _normalizePathTagsConfig(raw.get('path_tags'))

    return dict(config_path=config_path,
                crawl_root=crawl_root,
                crawl_include=include,
                crawl_exclude=exclude,
                path_tags=path_tags)


def loadAnkiDmConfig(src_dir):
    return _loadAnkiDmConfig(src_dir)


def _normalizePathForMatch(path):
    return str(path).replace('\\', '/')


def _matchesAny(path, patterns):
    normalized = _normalizePathForMatch(path)
    for pattern in patterns:
        if fnmatch.fnmatch(normalized, pattern):
            return True
    return False


def _findDataFiles(config):
    crawl_root = config['crawl_root']
    include_patterns = config['crawl_include']
    exclude_patterns = config['crawl_exclude']

    result = []
    known = set()

    for pattern in include_patterns:
        full_pattern = os.path.join(crawl_root, pattern)
        for path in glob.glob(full_pattern, recursive=True):
            if not os.path.isfile(path):
                continue

            rel_path = _normalizePathForMatch(os.path.relpath(path, crawl_root))
            if _matchesAny(rel_path, exclude_patterns):
                continue
            if rel_path in known:
                continue

            known.add(rel_path)
            rel_dir = _normalizePathForMatch(os.path.dirname(rel_path))
            if rel_dir == '.':
                rel_dir = ''
            result.append(
                dict(path=path,
                     rel_path=rel_path,
                     rel_dir=rel_dir))

    result.sort(key=lambda item: item['rel_path'])
    return result


def _normalizeTags(raw):
    if not raw:
        return []
    if isinstance(raw, list):
        tags = []
        for tag in raw:
            if tag is None:
                continue
            text = str(tag).strip()
            if text:
                tags.append(text)
        return tags
    if isinstance(raw, str):
        return [tag for tag in raw.split(' ') if tag]
    return [str(raw)]


def _sanitizeTagToken(raw):
    token = str(raw).strip().replace(' ', '_')
    token = TAG_SANITIZE_RE.sub('_', token)
    return token.strip('_')


def _mergeTags(tag_groups):
    result = []
    known = set()
    for tags in tag_groups:
        for tag in tags:
            if tag and tag not in known:
                result.append(tag)
                known.add(tag)
    return result


def _splitPath(raw_path):
    if not raw_path:
        return []
    path = str(raw_path).strip().replace('\\', '/')
    return [part for part in path.split('/') if part and part not in ('.', '..')]


def _segmentAt(parts, index):
    if index < 0 or index >= len(parts):
        return None
    return parts[index]


def _hierarchicalTag(prefix, value):
    base = _sanitizeTagToken(prefix)
    values = []
    for part in str(value).split('::'):
        token = _sanitizeTagToken(part)
        if token:
            values.append(token)
    if not base:
        return '::'.join(values)
    return '::'.join([base] + values) if values else base


def _deriveTagsFromPath(raw_path, config):
    parts = _splitPath(raw_path)
    if not parts:
        return []

    level_values = dict()
    reserved = set()
    for level in config['levels']:
        reserved.add(level['index'])
        value = _segmentAt(parts, level['index'])
        if value:
            level_values[level['name']] = value

    tags = []
    for level in config['levels']:
        value = level_values.get(level['name'])
        if not value:
            continue

        if level['emit_value_tag']:
            if level['value_tag_prefix']:
                tag = _hierarchicalTag(level['value_tag_prefix'], value)
            else:
                tag = _sanitizeTagToken(value)
            if tag:
                tags.append(tag)

        if level['tag_name']:
            context = dict(level_values)
            context['value'] = value
            try:
                tag_value = level['value_template'].format(**context)
            except Exception as err:
                util.err(
                    "Cannot format value_template for level '%s' and path '%s': %s"
                    % (level['name'], raw_path, err))
            tag = _hierarchicalTag(level['tag_name'], tag_value)
            if tag:
                tags.append(tag)

    if config['include_other_segments']:
        for idx, value in enumerate(parts):
            if idx in reserved:
                continue
            tag = _sanitizeTagToken(value)
            if tag:
                tags.append(tag)

    return _mergeTags([tags])


def _loadModels(src_dir):
    models_path = os.path.join(src_dir, 'models.yaml')
    data = util.getYaml(models_path, required=True)
    if not isinstance(data, dict):
        util.err("'models.yaml' must contain a top-level object.")

    raw_models = data.get('models')
    if not isinstance(raw_models, list) or not raw_models:
        util.err("'models.yaml' must contain a non-empty 'models' list.")

    models = dict()
    for i, raw_model in enumerate(raw_models):
        if not isinstance(raw_model, dict):
            util.err("Invalid model at index %d in 'models.yaml'." % (i,))

        model_id = raw_model.get('id')
        if not isinstance(model_id, str) or not model_id.strip():
            util.err("Invalid model id at index %d: %s" % (i, model_id))
        model_id = model_id.strip()
        if model_id in models:
            util.err("Duplicate model id in 'models.yaml': %s" % (model_id,))

        name = raw_model.get('name')
        if not isinstance(name, str) or not name.strip():
            util.err("Invalid model name for '%s': %s" % (model_id, name))
        name = name.strip()

        uuid = raw_model.get('uuid')
        if not isinstance(uuid, str) or not uuid.strip():
            util.err("Missing uuid for model '%s' in 'models.yaml'." %
                     (model_id,))
        uuid = uuid.strip()

        info = raw_model.get('info') or {}
        if not isinstance(info, dict):
            util.err("Invalid model info for '%s': %s" % (model_id, info))

        fields = raw_model.get('fields')
        if not isinstance(fields, list) or not fields:
            util.err("Model '%s' must define non-empty 'fields'." % (model_id,))
        fields = [str(field) for field in fields]
        for field in fields:
            util.checkFieldName(field)

        templates = raw_model.get('templates')
        if not isinstance(templates, list) or not templates:
            util.err("Model '%s' must define non-empty 'templates'." %
                     (model_id,))
        normalized_templates = []
        for t_idx, template in enumerate(templates):
            if not isinstance(template, dict):
                util.err("Invalid template #%d for model '%s'." %
                         (t_idx, model_id))
            t_name = template.get('name')
            if not isinstance(t_name, str) or not t_name.strip():
                util.err("Invalid template name in model '%s'." % (model_id,))
            normalized_templates.append(
                dict(name=t_name,
                     qfmt=template.get('qfmt') or '',
                     afmt=template.get('afmt') or '',
                     bqfmt=template.get('bqfmt') or '',
                     bafmt=template.get('bafmt') or '',
                     did=template.get('did')))

        models[model_id] = dict(id=model_id,
                                name=name,
                                uuid=uuid,
                                info=info,
                                fields=fields,
                                templates=normalized_templates,
                                css=raw_model.get('css') or '')

    return models


def _loadNotes(config):
    notes = []
    for data_file in _findDataFiles(config):
        data = util.getYaml(data_file['path'], required=True)
        if not isinstance(data, dict):
            util.err("File '%s' must contain a top-level object." %
                     (data_file['path'],))

        file_notes = data.get('notes')
        if not isinstance(file_notes, list):
            util.err("File '%s' must contain a 'notes' list." %
                     (data_file['path'],))

        for i, note in enumerate(file_notes):
            if not isinstance(note, dict):
                util.err("Invalid note at index %d in '%s'." %
                         (i, data_file['path']))
            notes.append(
                dict(note=note,
                     note_index=i,
                     source_file=data_file['path'],
                     source_rel_file=data_file['rel_path'],
                     source_rel_dir=data_file['rel_dir']))
    return notes


def loadCrawledNotes(config):
    return _loadNotes(config)


def _noteRef(note_entry):
    return "%s#%d" % (note_entry['source_rel_file'], note_entry['note_index'])


def _noteLanguages(note_entry):
    note = note_entry['note']
    fields_by_lang = note.get('fields_by_lang') or {}
    if not isinstance(fields_by_lang, dict):
        util.err("Invalid fields_by_lang for note '%s'." % (_noteRef(note_entry),))

    langs = set()
    for code, value in fields_by_lang.items():
        if not isinstance(code, str) or not code.strip():
            util.err("Invalid language code on note '%s': %s" %
                     (_noteRef(note_entry), code))
        if not isinstance(value, dict):
            util.err("fields_by_lang['%s'] must be an object on note '%s'." %
                     (code, _noteRef(note_entry)))
        langs.add(code)
    return langs


def _supportedLanguages(note_entries):
    langs = {'default'}
    for note_entry in note_entries:
        langs.update(_noteLanguages(note_entry))
    return sorted(langs)


def _fieldValuesForLang(note_entry, lang):
    note = note_entry['note']
    fields = note.get('fields')
    if not isinstance(fields, dict):
        util.err("Note '%s' is missing object field 'fields'." %
                 (_noteRef(note_entry),))

    resolved = dict(fields)
    if lang != 'default':
        fields_by_lang = note.get('fields_by_lang') or {}
        localized = fields_by_lang.get(lang)
        if localized:
            if not isinstance(localized, dict):
                util.err(
                    "Localized fields for lang '%s' must be an object on note '%s'."
                    % (lang, _noteRef(note_entry)))
            resolved.update(localized)
    return resolved


def _collectDeckMedia(media_files, values):
    result = []
    seen = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        for media_file in media_files:
            if media_file in seen:
                continue
            if text and media_file in text:
                seen.add(media_file)
                result.append(media_file)
    return result


def _normalizeDeckModels(deck_build, global_models):
    deck_models = deck_build.get('models')
    if not isinstance(deck_models, dict) or not deck_models:
        util.err("Deck build file is missing required 'models' map.")

    normalized = dict()
    for model_id, config in deck_models.items():
        if model_id not in global_models:
            util.err("Deck references unknown model '%s'." % (model_id,))
        if not isinstance(config, dict):
            util.err("Invalid model config for '%s' in deck build file." %
                     (model_id,))

        uuid = config.get('uuid')
        if not isinstance(uuid, str) or not uuid.strip():
            util.err("Model '%s' is missing uuid in deck build file." %
                     (model_id,))

        name = config.get('name') or global_models[model_id]['name']
        normalized[model_id] = dict(uuid=uuid.strip(), name=str(name))

    return normalized


def _noteModelInfo(model, model_uuid, model_name):
    fields_info = []
    for i, field in enumerate(model['fields']):
        entry = dict(name=field, ord=i)
        entry.update(util.getFieldDefaults())
        fields_info.append(entry)

    templates_info = []
    for i, template in enumerate(model['templates']):
        item = dict(template)
        item['ord'] = i
        templates_info.append(item)

    note_model = {
        '__type__': 'NoteModel',
        'crowdanki_uuid': model_uuid,
        'name': model_name,
        'flds': fields_info,
        'tmpls': templates_info,
        'css': model.get('css') or ''
    }
    note_model.update(model.get('info') or {})
    if 'vers' not in note_model:
        note_model['vers'] = []
    return note_model


def _loadGuidMap(src_dir):
    guid_map_path = os.path.join(src_dir, DEFAULT_GUID_MAP_FILE)
    raw = util.getYaml(guid_map_path, required=False)
    if raw is None:
        return {}, guid_map_path
    if not isinstance(raw, dict):
        util.err("File '%s' must contain a top-level object." %
                 (guid_map_path,))

    map_data = raw.get('guids')
    if map_data is None:
        map_data = raw
    if not isinstance(map_data, dict):
        util.err("File '%s' must contain a 'guids' object." % (guid_map_path,))

    guid_map = {}
    for key, value in map_data.items():
        if not isinstance(key, str) or not key.strip():
            util.err("Invalid guid-map key in '%s': %s" % (guid_map_path, key))
        if not isinstance(value, str) or not value.strip():
            util.err("Invalid guid-map value for key '%s' in '%s'." %
                     (key, guid_map_path))
        guid_map[key.strip()] = value.strip()

    return guid_map, guid_map_path


def _writeGuidMap(path, guid_map):
    ordered = dict((key, guid_map[key]) for key in sorted(guid_map.keys()))
    with open(path, 'w') as f:
        f.write(util.toYaml(dict(guids=ordered)))


def _deterministicGuidForKey(key, salt=0):
    seed = key if salt == 0 else "%s#%d" % (key, salt)
    digest = hashlib.sha256(seed.encode('utf-8')).digest()
    alphabet = util.GUID_CHARS
    value = int.from_bytes(digest, byteorder='big')

    chars = []
    while value > 0 and len(chars) < 12:
        value, mod = divmod(value, len(alphabet))
        chars.append(alphabet[mod])

    while len(chars) < 12:
        chars.append(alphabet[0])

    return ''.join(chars)


def _deterministicUniqueGuidForKey(key, used_guids):
    salt = 0
    while True:
        guid = _deterministicGuidForKey(key, salt)
        if guid not in used_guids:
            return guid
        salt += 1


def _noteGuidKey(note_entry):
    note = note_entry['note']
    note_id = note.get('id')
    if note_id is not None:
        if not isinstance(note_id, str) or not note_id.strip():
            util.err("Invalid note id on '%s': %s" % (_noteRef(note_entry),
                                                      note_id))
        return 'id:%s#%s' % (note_entry['source_rel_file'], note_id.strip())
    return 'idx:%s#%d' % (note_entry['source_rel_file'], note_entry['note_index'])


def _assignNoteGuids(note_entries, src_dir, full=False):
    guid_map, guid_map_path = _loadGuidMap(src_dir)
    used_guids = set()
    discovered_keys = set()
    next_guid_map = dict()

    for note_entry in note_entries:
        key = _noteGuidKey(note_entry)
        if key in discovered_keys:
            util.err("Duplicate note identity key found: %s" % (key,))
        discovered_keys.add(key)

        existing_guid = guid_map.get(key)
        if (not full and isinstance(existing_guid, str) and existing_guid
                and existing_guid not in used_guids):
            guid = existing_guid
        else:
            guid = _deterministicUniqueGuidForKey(key, used_guids)

        used_guids.add(guid)
        next_guid_map[key] = guid
        note_entry['guid'] = guid

    changed = next_guid_map != guid_map
    if changed:
        _writeGuidMap(guid_map_path, next_guid_map)

    return dict(changed=changed, path=guid_map_path)


def reindexGuidMap(note_entries, src_dir, full=False):
    return _assignNoteGuids(note_entries, src_dir, full=full)


def build(decks, src_dir, build_dir, lang):
    ankidm_config = _loadAnkiDmConfig(src_dir)
    notes = _loadNotes(ankidm_config)
    guid_update = _assignNoteGuids(notes, src_dir, full=False)
    if guid_update['changed']:
        util.msg("Updated guid map: %s" % (os.path.basename(guid_update['path']),))

    glbals = dict(deck=util.getJson(os.path.join(src_dir, 'deck.json')),
                  config=util.getJson(os.path.join(src_dir, 'config.json')),
                  media=util.getFilesList(os.path.join(src_dir, 'media')),
                  models=_loadModels(src_dir),
                  desc=util.getRaw(os.path.join(src_dir, 'desc.html')),
                  notes=notes)

    path_tags_config = ankidm_config['path_tags']

    languages = _supportedLanguages(glbals['notes'])
    if lang:
        if lang not in languages:
            util.err("Language '%s' is not available." % (lang,))
        languages = [lang]

    decks_build = _readDecks(decks, os.path.join(src_dir, 'decks'))

    for language in languages:
        for deck, deck_build in decks_build.items():
            util.msg("Building deck: %s (Language: %s)" % (deck, language))

            if 'deck' not in deck_build or 'config' not in deck_build:
                util.err(
                    "Deck build file is missing required 'deck'/'config' sections."
                )

            deck_uuid = util.uuidEncode(deck_build['deck']['uuid'], language)
            config_uuid = util.uuidEncode(deck_build['config']['uuid'], language)

            deck_models = _normalizeDeckModels(deck_build, glbals['models'])
            localized_model_uuids = {
                model_id: util.uuidEncode(config['uuid'], language)
                for model_id, config in deck_models.items()
            }

            deck_data = {
                '__type__': 'Deck',
                'crowdanki_uuid': deck_uuid,
                'name': util.filenameToDeck(deck if language == 'default' else
                                            "%s[%s]" % (deck, language)),
                'desc': deck_build.get('@desc') or glbals['desc']
            }
            deck_data.update(glbals['deck'])
            deck_data.update(deck_build['@deck'])

            deck_data['deck_configurations'] = [{
                '__type__': 'DeckConfig',
                'crowdanki_uuid': config_uuid,
                'name': deck_build['config']['name']
            }]
            deck_data['deck_configurations'][-1].update(glbals['config'])
            deck_data['deck_configurations'][-1].update(deck_build['@config'])
            deck_data['deck_config_uuid'] = config_uuid

            deck_data['note_models'] = []
            for model_id, deck_model in deck_models.items():
                model = glbals['models'][model_id]
                deck_data['note_models'].append(
                    _noteModelInfo(model, localized_model_uuids[model_id],
                                   deck_model['name']))

            deck_notes = []
            deck_media = []
            seen_media = set()
            seen_guids = set()
            for note_entry in glbals['notes']:
                note = note_entry['note']
                model_id = note.get('model')
                if model_id not in glbals['models']:
                    util.err("Note '%s' references unknown model '%s'." %
                             (_noteRef(note_entry), model_id))
                if model_id not in localized_model_uuids:
                    util.err("Note '%s' uses model '%s' not enabled for deck '%s'." %
                             (_noteRef(note_entry), model_id, deck))

                model = glbals['models'][model_id]
                fields_by_name = _fieldValuesForLang(note_entry, language)
                fields = []
                for field_name in model['fields']:
                    if field_name not in fields_by_name:
                        util.err(
                            "Missing field '%s' in note '%s' for model '%s'." %
                            (field_name, _noteRef(note_entry), model_id))
                    fields.append(fields_by_name[field_name])

                for media_file in _collectDeckMedia(glbals['media'], fields):
                    if media_file not in seen_media:
                        seen_media.add(media_file)
                        deck_media.append(media_file)

                tags = _normalizeTags(note.get('tags'))
                if path_tags_config:
                    tags = _mergeTags(
                        [tags,
                         _deriveTagsFromPath(note_entry['source_rel_dir'],
                                             path_tags_config)])

                decoded_guid = util.guidDecode(note_entry['guid'],
                                               localized_model_uuids[model_id])
                if decoded_guid in seen_guids:
                    util.err(
                        "Duplicate guid generated for note '%s'. Run 'index --full'."
                        % (_noteRef(note_entry),))
                seen_guids.add(decoded_guid)

                deck_notes.append({
                    '__type__': 'Note',
                    'data': '',
                    'fields': fields,
                    'flags': 0,
                    'guid': decoded_guid,
                    'note_model_uuid': localized_model_uuids[model_id],
                    'tags': tags
                })

            deck_data['media_files'] = deck_media
            deck_data['notes'] = deck_notes

            localized_deck = deck if language == 'default' else '_'.join(
                (deck, language))
            target_build_dir = build_dir or 'build'
            deck_dir = os.path.join(target_build_dir, localized_deck)
            util.prepareDir(deck_dir)
            with open(os.path.join(deck_dir, localized_deck + '.json'), 'w') as f:
                f.write(util.toJson(deck_data))

            util.prepareDir(os.path.join(deck_dir, 'media'))
            for media_file in deck_media:
                shutil.copy(os.path.join(src_dir, 'media', media_file),
                            os.path.join(deck_dir, 'media', media_file))


def _readDecks(decks, directory):
    decks_data = dict()

    if not decks:
        decks = util.getFilesList(directory)

    for deck in decks:
        deck_filename = util.deckToFilename(deck)
        dirnm = os.path.join(directory, deck_filename)
        if os.path.exists(dirnm) and os.path.isdir(dirnm):
            decks_data[deck_filename] = _readDeck(dirnm)
        else:
            util.err("Deck not found: %s" % (dirnm,))

    return decks_data


def _readDeck(directory):
    inDir = lambda fn: os.path.join(directory, fn)
    deck_data = util.getJson(inDir('build.json'), required=False)
    if not isinstance(deck_data, dict):
        deck_data = {}
    deck_data['@deck'] = util.getJson(inDir('deck.json'), required=False)
    deck_data['@config'] = util.getJson(inDir('config.json'), required=False)
    deck_data['@desc'] = util.getRaw(inDir('info.html'), required=False)
    if not isinstance(deck_data['@deck'], dict):
        deck_data['@deck'] = {}
    if not isinstance(deck_data['@config'], dict):
        deck_data['@config'] = {}
    return deck_data
