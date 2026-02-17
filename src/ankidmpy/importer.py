import ankidmpy.util as util
from collections import defaultdict
import shutil
import re
import os.path

MODEL_ID_RE = re.compile(r'[^0-9A-Za-z_]+')


def _makeModelId(model_name, known_ids):
    base = MODEL_ID_RE.sub('_', str(model_name).strip().lower()).strip('_')
    if not base:
        base = 'model'
    model_id = base
    idx = 2
    while model_id in known_ids:
        model_id = '%s_%d' % (base, idx)
        idx += 1
    return model_id


def importIt(path, directory, deck=None):
    path = path.rstrip('/')
    _, basename = os.path.split(path)
    filenm = os.path.join(path, basename + '.json')
    if not os.path.exists(filenm):
        filenm = os.path.join(path, 'deck.json')

    directory = directory.rstrip('/')
    if not directory:
        directory = 'src'

    build_info = defaultdict(dict)

    deck_data = util.getJson(filenm)

    if len(deck_data['deck_configurations']) > 1:
        util.err("Multiple deck configurations per deck is not supported")

    if len(deck_data['deck_configurations']) == 0 or len(
            deck_data['note_models']) == 0:
        util.err(
            "Decks with empty models or configurations are note supported.  Try adding one card in your deck."
        )

    build_info['deck']['uuid'] = util.createUuid()

    dictSlice = lambda d, kys: {key: d[key] for key in d.keys() & kys}

    deck_info = dictSlice(deck_data, {'dyn', 'extendNew', 'extendRev'})
    deck_info['children'] = []
    with open(os.path.join(directory, 'deck.json'), 'w') as f:
        f.write(util.toJson(deck_info))

    configuration = deck_data['deck_configurations'][0]
    build_info['config']['uuid'] = util.createUuid()
    build_info['config']['name'] = configuration['name']
    configuration_info = dictSlice(configuration, {
        'autoplay', 'dyn', 'lapse', 'maxTaken', 'new', 'replayq', 'rev', 'timer'
    })
    with open(os.path.join(directory, 'config.json'), 'w') as f:
        f.write(util.toJson(configuration_info))

    desc = deck_data['desc']
    with open(os.path.join(directory, 'desc.html'), 'w') as f:
        f.write(desc)

    models_data = []
    model_uuid_to_id = dict()
    model_by_id = dict()
    build_info['models'] = dict()
    for model in deck_data['note_models']:
        model_id = _makeModelId(model.get('name') or 'model', model_by_id)
        model_build_uuid = util.createUuid()
        build_info['models'][model_id] = dict(uuid=model_build_uuid,
                                              name=model['name'])
        model_uuid_to_id[model['crowdanki_uuid']] = model_id

        model_info = dictSlice(model, {'latexPost', 'latexPre', 'type', 'vers'})
        if 'vers' not in model_info:
            model_info['vers'] = []

        fields = []
        for field in model['flds']:
            fields.append(util.checkFieldName(field['name']))

        templates = []
        for template in model['tmpls']:
            template_data = dictSlice(template,
                                      {'name', 'qfmt', 'afmt', 'bafmt', 'bqfmt',
                                       'did'})
            template_data['bafmt'] = template_data.get('bafmt') or ''
            template_data['bqfmt'] = template_data.get('bqfmt') or ''
            template_data['did'] = template_data.get('did')
            templates.append(template_data)

        model_data = dict(id=model_id,
                          name=model['name'],
                          uuid=model_build_uuid,
                          info=model_info,
                          fields=fields,
                          templates=templates,
                          css=model.get('css') or '')
        models_data.append(model_data)
        model_by_id[model_id] = model_data

    with open(os.path.join(directory, 'models.yaml'), 'w') as f:
        f.write(util.toYaml(dict(models=models_data)))

    with open(os.path.join(directory, 'ankidm.yaml'), 'w') as f:
        f.write(
            util.toYaml(
                dict(crawl=dict(root='.',
                                include=['**/data.yaml'],
                                exclude=['build/**']))))

    notes_data = []
    guid_map = dict()
    rel_data_file = 'data.yaml'
    for i, note in enumerate(deck_data['notes']):
        model_uuid = note.get('note_model_uuid')
        if model_uuid not in model_uuid_to_id:
            util.err("Cannot find note model for note: %s" %
                     (note.get('guid') or '<missing-guid>',))
        model_id = model_uuid_to_id[model_uuid]
        model_data = model_by_id[model_id]
        field_names = model_data['fields']
        if len(note['fields']) != len(field_names):
            util.err(
                "Field count mismatch for note '%s' in model '%s'. Expected %d fields, got %d."
                % (note.get('guid') or '<missing-guid>', model_data['name'],
                   len(field_names), len(note['fields'])))

        fields_data = dict()
        for field_idx, field_name in enumerate(field_names):
            fields_data[field_name] = note['fields'][field_idx]

        tags = note.get('tags') or []
        if not isinstance(tags, list):
            tags = [tag for tag in str(tags).split(' ') if tag]

        guid_map['idx:%s#%d' %
                 (rel_data_file, i)] = util.guidEncode(
                     note['guid'], build_info['models'][model_id]['uuid'])
        notes_data.append(
            dict(model=model_id,
                 fields=fields_data,
                 tags=tags))

    with open(os.path.join(directory, 'data.yaml'), 'w') as f:
        f.write(util.toYaml(dict(notes=notes_data)))
    with open(os.path.join(directory, 'guid-map.yaml'), 'w') as f:
        f.write(util.toYaml(dict(guids=guid_map)))

    media_files = deck_data['media_files']
    util.prepareDir(os.path.join(directory, 'media'))
    for media_file in media_files:
        shutil.copy(os.path.join(path, 'media', media_file),
                    os.path.join(directory, 'media', media_file))

    if deck:
        deck_name = deck
    else:
        deck_name = deck_data['name']
        deck = deck_name

    deck_dir_name = util.deckToFilename(deck_name)
    fulldirname = os.path.join(directory, 'decks', deck_dir_name)
    util.prepareDir(fulldirname)

    with open(os.path.join(fulldirname, 'build.json'), 'w') as f:
        f.write(util.toJson(build_info))

    util.msg("Created deck: %s" % (deck,))
