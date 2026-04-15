#!/bin/bash
# Rename FMS files to remove version suffixes

cd /Users/nuin/Projects/alliance/agr_intermine_builder/docker/alliancemine-unified/data/fms || exit 1

echo "Renaming files to remove version suffixes..."

# Rename files with pattern: NAME_<digit>.EXT -> NAME.EXT
for file in *_[0-9].*; do
    if [ -f "$file" ]; then
        # Extract base name and extension
        new_name=$(echo "$file" | sed 's/_[0-9]\+\././')
        
        # Only rename if the new name is different and doesn't already exist
        if [ "$file" != "$new_name" ] && [ ! -f "$new_name" ]; then
            echo "  $file -> $new_name"
            mv "$file" "$new_name"
        fi
    fi
done

echo "Done!"
