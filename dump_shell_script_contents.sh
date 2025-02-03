#!/bin/bash

# Use the current directory as the search directory
SEARCH_DIR=$(pwd)

# Allow output file to be specified as argument, otherwise use default
OUTPUT_FILE="${1:-output.txt}"

echo "Searching in $SEARCH_DIR for .sh files..."

# Initialize or clear the output file with error handling
if ! echo "" > "$OUTPUT_FILE"; then
    echo "Error: Unable to create/write to $OUTPUT_FILE"
    exit 1
fi

# Store file list first to check if any files were found
files=$(find "$SEARCH_DIR" -maxdepth 1 -type f -name "*.sh")

if [ -z "$files" ]; then
    echo "No .sh files found in $SEARCH_DIR"
    exit 0
fi

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
