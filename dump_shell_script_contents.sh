#!/bin/bash

# Use the current directory as the search directory
SEARCH_DIR=$(pwd)

# Specify the output file where the contents will be dumped
OUTPUT_FILE="output.txt"

echo "Searching in $SEARCH_DIR for .sh files..."

# Initialize or clear the output file before starting the loop
echo "" > "$OUTPUT_FILE"

# Find all .sh files in the current directory only and process them
find "$SEARCH_DIR" -maxdepth 1 -type f -name "*.sh" | while read -r filename; do
    # Skip the output file itself to prevent infinite growth
    if [ "$(basename "$filename")" = "$OUTPUT_FILE" ]; then
        continue
    fi
    
    echo "Processing: $(basename "$filename")"
    
    # Write the file name to the output file
    echo "File Name: $filename" >> "$OUTPUT_FILE"
    echo "----------------------------" >> "$OUTPUT_FILE"
    cat "$filename" >> "$OUTPUT_FILE"
    echo -e "\n----------------------------\n" >> "$OUTPUT_FILE"
done

echo "All .sh files have been processed and their contents saved to $OUTPUT_FILE."
