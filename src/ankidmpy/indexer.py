import ankidmpy.builder as builder
import ankidmpy.util as util
import os.path


def indexIt(full, base):
    config = builder.loadAnkiDmConfig(base)
    notes = builder.loadCrawledNotes(config)
    result = builder.reindexGuidMap(notes, base, full=full)

    if result['changed']:
        util.msg("Successfully reindexed '%s' (added: %d, removed: %d, reassigned: %d)"
                 % (os.path.basename(result['path']), result['added_count'],
                    result['removed_count'], result['reassigned_count']))
        if result['removed_count'] > 0:
            util.warn("Removed stale guid-map keys (first %d): %s" %
                      (len(result['removed_examples']),
                       ', '.join(result['removed_examples'])))
    else:
        util.msg("No guid changes needed in '%s'" % (os.path.basename(result['path']),))
