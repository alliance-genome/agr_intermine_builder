#!/usr/bin/env sh

## Parse a docker-compose config YAML file and create the directories listed
## as volumes. This is useful since the directories need to exist for their
## permissions to be preserved (otherwise the docker daemon would create them
## as root). Doing this is the only way to have volume directories which are
## owned by a user ID determined during container runtime, usually as the
## logged in user so that you can share files between the user and the docker
## container without running into permission problems.

if [ -z $1 ]; then
  echo "Usage: ${0} docker-compose.yml"
  echo "This script creates the directories listed as volumes in the docker-compose config file passed as argument."
  exit 1;
fi

# Add error checking for file existence
if [ ! -f "$1" ]; then
  echo "Error: File '$1' does not exist"
  exit 1
fi

# Add quotes around $1 to handle filenames with spaces
awk 'BEGIN {FS="\n"} {
  for (i=1; i<=NF; i++) {
    if ($i ~ /^ *volumes:/) {
      reading=1
    } else if (reading) {
      if ($i ~ /^ *-/) {
        start=index($i, "-")+2
        count=index($i, ":")-start
        print substr($i, start, count)
      } else if ($i !~ /^ *#/) {
        reading=0
      }
    }
  }
}' "$1" | xargs mkdir -p
