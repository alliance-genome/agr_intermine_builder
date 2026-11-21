#!/bin/sh
# Installed as /usr/local/bin/ssh. project_build runs its checkpoint commands as
# `ssh <dump_host> createdb ...`; RDS has no SSH, so drop the host and run the command here.
#
# A checkpoint is `createdb ... -T <db> <db>:<step>`. Once it succeeds, every step since the
# previous checkpoint has passed, so the older <db>:* copies are dropped: `project_build -l`
# only ever restores the newest one, and each copy is a full copy of the build database.
# Set KEEP_ALL_CHECKPOINTS=true to keep them all.
#
# Any other ssh call (the Solr core preflight passes -i/-o options and user@host first) goes to
# the real client; the dump host project_build passes is a bare hostname. project_build calls
# ssh only when that host is not "localhost", so build_full.py passes "rds".
case "$1" in
    -* | *@*) exec "${SSH_REAL:-/usr/bin/ssh}" "$@" ;;
esac
shift
# Like real ssh, join the words and run them in a shell: dump_db and the restart-file lookup
# pass the whole command as one string ("pg_dump -F c ...", "ls -1 /root/data/dump.*").
sh -c "$*" || exit $?

[ "$1" = createdb ] || exit 0
[ "${KEEP_ALL_CHECKPOINTS:-false}" = true ] && exit 0

user= host= template= target=
while [ $# -gt 1 ]; do
    case "$1" in
        -U) user=$2; shift ;;
        -h) host=$2; shift ;;
        -T) template=$2; shift ;;
    esac
    shift
done
target=$1

case "$target" in
    "$template":*) ;;
    *) exit 0 ;;
esac

psql -U "$user" -h "$host" -d postgres -At -c \
    "SELECT datname FROM pg_database WHERE starts_with(datname, '${template}:') AND datname <> '${target}'" |
while read -r old; do
    # stderr: project_build dies when a spawned command prints "error" on stdout
    echo "checkpoint $target done - dropping older checkpoint $old" >&2
    dropdb -U "$user" -h "$host" "$old" || echo "WARN: could not drop $old" >&2
done
exit 0
