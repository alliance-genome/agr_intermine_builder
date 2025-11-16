#!/bin/bash

TARGET_DIR="$1"

if [ -z "$TARGET_DIR" ]; then
    echo "Usage: $0 <target_directory>"
    exit 1
fi

# Create FTP directory structure
mkdir -p "$TARGET_DIR/species"
mkdir -p "$TARGET_DIR/ONTOLOGY"
mkdir -p "$TARGET_DIR/acedb/WS298"

# Function to find and copy file to specific path
find_and_copy() {
    local filename="$1"
    local target_path="$2"

    echo "Finding: $filename"
    found=$(find /usr/local/ftp/pub/wormbase/releases/WS298 -name "$filename" 2>/dev/null | head -1)
    if [ -n "$found" ]; then
        echo "  Found: $found"
        cp "$found" "$target_path"
    else
        echo "  NOT FOUND"
    fi
}

# Protein FASTA files -> species/
echo "=== Protein Files ==="
find_and_copy "c_elegans.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "c_brenneri.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "c_briggsae.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "c_japonica.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "c_remanei.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "b_malayi.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "o_volvulus.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "s_ratti.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "p_pacificus.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "t_spiralis.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "t_muris.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "h_contortus.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "o_tipulae.WS298.protein.fa.gz" "$TARGET_DIR/species/"
find_and_copy "p_redivivus.WS298.protein.fa.gz" "$TARGET_DIR/species/"

# C. elegans specific files -> species/c_elegans/
mkdir -p "$TARGET_DIR/species/c_elegans/PRJNA13758"
echo "=== C. elegans Files ==="
find_and_copy "c_elegans.WS298.genomic.fa.gz" "$TARGET_DIR/species/c_elegans/PRJNA13758/"
find_and_copy "c_elegans.WS298.mRNA_transcripts.fa.gz" "$TARGET_DIR/species/c_elegans/PRJNA13758/"
find_and_copy "c_elegans.WS298.CDS_transcripts.fa.gz" "$TARGET_DIR/species/c_elegans/PRJNA13758/"
find_and_copy "c_elegans.WS298.annotations.gff3.gz" "$TARGET_DIR/species/c_elegans/PRJNA13758/"

# Ontology files -> ONTOLOGY/
echo "=== Ontology Files ==="
find_and_copy "gene_ontology.WS298.obo" "$TARGET_DIR/ONTOLOGY/"
find_and_copy "anatomy_ontology.WS298.obo" "$TARGET_DIR/ONTOLOGY/"
find_and_copy "disease_ontology.WS298.obo" "$TARGET_DIR/ONTOLOGY/"
find_and_copy "phenotype_ontology.WS298.obo" "$TARGET_DIR/ONTOLOGY/"
find_and_copy "gene_association.WS298.wb.gz" "$TARGET_DIR/ONTOLOGY/"

# AceDB XML files -> acedb/WS298/
echo "=== AceDB XML Files ==="
find_and_copy "elegans_Genomic_canonical.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_DNA-canonical.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Protein-canonical.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_CDS-canonical.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Transcript-canonical.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Pseudogene-canonical.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Feature_data-canonical.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Variation.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_RNAi.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Phenotype.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Expression-pattern.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Reference.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Person.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Disease.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Interaction.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Rearrangement.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Strain.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Clone.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Transgene.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Expr_cluster.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Oligo_set.xml.gz" "$TARGET_DIR/acedb/WS298/"
find_and_copy "elegans_Microarray_results.xml.gz" "$TARGET_DIR/acedb/WS298/"

echo "Done. Files copied with FTP structure to: $TARGET_DIR"
