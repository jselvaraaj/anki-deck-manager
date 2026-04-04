import ankidmpy.builder as builder
import ankidmpy.util as util
import os
import os.path


def _parseCrowdAnki(crowdanki_path):
    crowdanki_path = crowdanki_path.rstrip('/')
    _, basename = os.path.split(crowdanki_path)
    filenm = os.path.join(crowdanki_path, basename + '.json')
    if not os.path.exists(filenm):
        filenm = os.path.join(crowdanki_path, 'deck.json')
    return util.getJson(filenm)


def _findDeckName(base):
    decks_dir = os.path.join(base, 'decks')
    decks = util.getFilesList(decks_dir, 'dir')
    if not decks:
        util.err("No decks found in '%s'." % decks_dir)
    if len(decks) > 1:
        util.err("Multiple decks found; specify --deck: %s" % ', '.join(decks))
    return decks[0]


def _loadDeckBuild(base, deck):
    deck_dirname = deck if deck else _findDeckName(base)
    build_path = os.path.join(base, 'decks', deck_dirname, 'build.json')
    data = util.getJson(build_path)
    if not isinstance(data, dict):
        util.err("Invalid build.json at '%s'." % build_path)
    return deck_dirname, data


def _parseKey(key):
    if key.startswith('id:'):
        rest = key[3:]
        sep = rest.rfind('#')
        if sep < 0:
            util.err("Malformed guid-map key: %s" % key)
        return rest[:sep], {'type': 'id', 'value': rest[sep + 1:]}
    elif key.startswith('idx:'):
        rest = key[4:]
        sep = rest.rfind('#')
        if sep < 0:
            util.err("Malformed guid-map key: %s" % key)
        return rest[:sep], {'type': 'idx', 'value': int(rest[sep + 1:])}
    else:
        util.err("Unknown guid-map key format: %s" % key)


def _relDir(rel_path):
    d = os.path.dirname(rel_path).replace('\\', '/')
    return '' if d in ('', '.') else d


def _stripPathTags(tags, rel_dir, path_tags_config):
    if not path_tags_config or not rel_dir:
        return list(tags)
    path_derived = set(builder._deriveTagsFromPath(rel_dir, path_tags_config))
    return [t for t in tags if t not in path_derived]


def _applyFileOps(file_ops, crawl_root, guid_map):
    for rel_path, ops in sorted(file_ops.items()):
        abs_path = os.path.join(crawl_root, rel_path)
        data = util.getYaml(abs_path, required=True)
        notes = data.get('notes', [])
        if not isinstance(notes, list):
            util.err("File '%s' must contain a 'notes' list." % abs_path)

        # Apply field/tag updates in-place (before any index shifts)
        for op in ops.get('updates', []):
            loc = op['locator']
            if loc['type'] == 'id':
                for note in notes:
                    if str(note.get('id', '')) == loc['value']:
                        note['fields'] = op['fields']
                        note['tags'] = op['tags']
                        break
                else:
                    util.warn("Could not find note with id '%s' in '%s' for update." %
                              (loc['value'], rel_path))
            else:
                idx = loc['value']
                if 0 <= idx < len(notes):
                    notes[idx]['fields'] = op['fields']
                    notes[idx]['tags'] = op['tags']
                else:
                    util.warn("Note index %d out of range in '%s' for update." %
                              (idx, rel_path))

        # Collect deletion indices
        delete_indices = set()
        for op in ops.get('deletions', []):
            loc = op['locator']
            if loc['type'] == 'id':
                found = False
                for i, note in enumerate(notes):
                    if str(note.get('id', '')) == loc['value']:
                        delete_indices.add(i)
                        found = True
                        break
                if not found:
                    util.warn("Could not find note with id '%s' in '%s' for deletion." %
                              (loc['value'], rel_path))
            else:
                delete_indices.add(loc['value'])

        # Rebuild notes list, shifting idx-based guid-map keys for surviving notes
        if delete_indices:
            new_notes = []
            new_idx = 0
            for old_idx, note in enumerate(notes):
                if old_idx in delete_indices:
                    continue
                old_key = 'idx:%s#%d' % (rel_path, old_idx)
                new_key = 'idx:%s#%d' % (rel_path, new_idx)
                if old_key in guid_map and old_key != new_key:
                    guid_map[new_key] = guid_map.pop(old_key)
                new_notes.append(note)
                new_idx += 1
            notes = new_notes

        data['notes'] = notes
        with open(abs_path, 'w') as f:
            f.write(util.toYaml(data))


def _applyAdditions(additions, crawl_root, new_notes_rel_path, guid_map):
    if not additions:
        return

    abs_path = os.path.join(crawl_root, new_notes_rel_path)
    if os.path.exists(abs_path):
        data = util.getYaml(abs_path, required=True)
        notes = data.get('notes', [])
        if not isinstance(notes, list):
            notes = []
    else:
        util.prepareDir(os.path.dirname(abs_path))
        data = {}
        notes = []

    for add_op in additions:
        new_idx = len(notes)
        note = {'model': add_op['model_id'], 'fields': add_op['fields']}
        if add_op['tags']:
            note['tags'] = add_op['tags']
        notes.append(note)

        key = 'idx:%s#%d' % (new_notes_rel_path, new_idx)
        guid_map[key] = util.guidEncode(add_op['crowdanki_guid'], add_op['model_uuid'])

    data['notes'] = notes
    with open(abs_path, 'w') as f:
        f.write(util.toYaml(data))


def syncIt(crowdanki_path, base, deck, new_notes_file, dry_run):
    ankidm_config = builder.loadAnkiDmConfig(base)
    crawl_root = ankidm_config['crawl_root']
    path_tags_config = ankidm_config['path_tags']

    guid_map, guid_map_path = builder._loadGuidMap(base)
    reverse_map = {v: k for k, v in guid_map.items()}

    _, build_data = _loadDeckBuild(base, deck)
    models_config = build_data.get('models') or {}
    if not models_config:
        util.err("build.json has no 'models' section.")
    uuid_to_model_id = {cfg['uuid']: mid for mid, cfg in models_config.items()}

    crowdanki_data = _parseCrowdAnki(crowdanki_path)

    # crowdanki_uuid → ordered field name list
    crowdanki_model_fields = {}
    for nm in crowdanki_data.get('note_models', []):
        crowdanki_model_fields[nm['crowdanki_uuid']] = [
            f['name'] for f in nm.get('flds', [])
        ]

    matched_keys = set()
    file_ops = {}
    additions = []

    for note in crowdanki_data.get('notes', []):
        crowdanki_guid = note.get('guid', '')
        model_uuid = note.get('note_model_uuid', '')

        if model_uuid not in uuid_to_model_id:
            util.warn("Skipping note with unknown model UUID: %s" % model_uuid)
            continue

        model_id = uuid_to_model_id[model_uuid]
        internal_guid = util.guidEncode(crowdanki_guid, models_config[model_id]['uuid'])

        field_names = crowdanki_model_fields.get(model_uuid, [])
        fields_data = dict(zip(field_names, note.get('fields', [])))
        crowdanki_tags = note.get('tags', [])

        if internal_guid in reverse_map:
            key = reverse_map[internal_guid]
            matched_keys.add(key)
            rel_path, locator = _parseKey(key)
            manual_tags = _stripPathTags(crowdanki_tags, _relDir(rel_path),
                                         path_tags_config)
            ops = file_ops.setdefault(rel_path, {'updates': [], 'deletions': []})
            ops['updates'].append({
                'locator': locator,
                'fields': fields_data,
                'tags': manual_tags,
            })
        else:
            new_rel_dir = _relDir(new_notes_file or 'data.yaml')
            manual_tags = _stripPathTags(crowdanki_tags, new_rel_dir, path_tags_config)
            additions.append({
                'model_id': model_id,
                'fields': fields_data,
                'tags': manual_tags,
                'crowdanki_guid': crowdanki_guid,
                'model_uuid': models_config[model_id]['uuid'],
            })

    deleted_keys = set()
    for key in guid_map:
        if key not in matched_keys:
            rel_path, locator = _parseKey(key)
            ops = file_ops.setdefault(rel_path, {'updates': [], 'deletions': []})
            ops['deletions'].append({'key': key, 'locator': locator})
            deleted_keys.add(key)

    n_updated = sum(len(ops['updates']) for ops in file_ops.values())
    n_deleted = len(deleted_keys)
    n_added = len(additions)
    target_file = new_notes_file or 'data.yaml'

    if dry_run:
        util.msg("Dry run — no changes written.")
        util.msg("  Updated notes: %d" % n_updated)
        util.msg("  Deleted notes: %d" % n_deleted)
        if n_deleted > 0:
            for key in sorted(deleted_keys):
                util.msg("    - %s" % key)
        util.msg("  New notes:     %d" % n_added)
        if n_added > 0:
            util.msg("  New notes target: %s" % target_file)
        return

    _applyFileOps(file_ops, crawl_root, guid_map)

    for key in deleted_keys:
        guid_map.pop(key, None)

    _applyAdditions(additions, crawl_root, target_file, guid_map)

    builder._writeGuidMap(guid_map_path, guid_map)

    util.msg("Sync complete: updated=%d, deleted=%d, added=%d" %
             (n_updated, n_deleted, n_added))
    if n_added > 0:
        util.msg("  New notes added to: %s" % target_file)
