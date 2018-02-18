try:
    # 'resource' is unix-only
    from resource import getrlimit, setrlimit, RLIMIT_NOFILE
except ImportError: # pragma: nocover
    getrlimit, setrlimit, RLIMIT_NOFILE = None, None, None # pragma: nocover
from twisted.python import log

def increase_rlimits():
    if getrlimit is None:
        log.msg("unable to import 'resource', leaving rlimit alone")
        return
    soft, hard = getrlimit(RLIMIT_NOFILE)
    if soft >= 10000:
        log.msg("RLIMIT_NOFILE.soft was %d, leaving it alone" % soft)
        return
    # OS-X defaults to soft=7168, and reports a huge number for 'hard',
    # but won't accept anything more than soft=10240, so we can't just
    # set soft=hard. Linux returns (1024, 1048576) and is fine with
    # soft=hard. Cygwin is reported to return (256,-1) and accepts up to
    # soft=3200. So we try multiple values until something works.
    for newlimit in [hard, 10000, 3200, 1024]:
        log.msg("changing RLIMIT_NOFILE from (%s,%s) to (%s,%s)" %
                (soft, hard, newlimit, hard))
        try:
            setrlimit(RLIMIT_NOFILE, (newlimit, hard))
            log.msg("setrlimit successful")
            return
        except ValueError as e:
            log.msg("error during setrlimit: %s" % e)
            continue
        except:
            log.msg("other error during setrlimit, leaving it alone")
            log.err()
            return
    log.msg("unable to change rlimit, leaving it alone")
