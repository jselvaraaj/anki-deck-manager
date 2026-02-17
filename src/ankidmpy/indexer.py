import ankidmpy.builder as builder
import ankidmpy.util as util
import os.path


def indexIt(full, base):
    config = builder.loadAnkiDmConfig(base)
    notes = builder.loadCrawledNotes(config)
    result = builder.reindexGuidMap(notes, base, full=full)

    if result['changed']:
        util.msg("Successfully reindexed '%s'" % (os.path.basename(result['path']),))
    else:
        util.msg("No guid changes needed in '%s'" % (os.path.basename(result['path']),))
