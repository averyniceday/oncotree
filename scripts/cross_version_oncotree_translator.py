import argparse
import csv
import os
import requests
import sys

#ONCOTREE_API_URL_BASE = "http://oncotree.mskcc.org/api/"
ONCOTREE_API_URL_BASE = "http://dashi-dev.cbio.mskcc.org:8080/manda-oncotree/api/"
ONCOTREE_VERSION_ENDPOINT = ONCOTREE_API_URL_BASE + "versions"
ONCOTREE_TUMORTYPES_ENDPOINT = ONCOTREE_API_URL_BASE + "tumorTypes"
VERSION_API_IDENTIFIER_FIELD = "api_identifier"
VERSION_RELEASE_DATE_FIELD = "release_date"
METADATA_HEADER_PREFIX = "#"

#--------------------------------------------------------------
# hit oncotree versions API to check if oncotree version exists - error and exit if not
def oncotree_version_exists(oncotree_version):
    response = requests.get(ONCOTREE_VERSION_ENDPOINT)
    if response.status_code != 200:
        print >> sys.stderr, "ERROR (HttpStatusCode %d): Unable to retrieve oncotree versions." % (response.status_code)
        sys.exit(1)
    all_oncotree_versions = [version[VERSION_API_IDENTIFIER_FIELD] for version in response.json()]
    return oncotree_version in all_oncotree_versions

#-------------------------------------------------------------
# hit oncotree versions API, compares source/target oncotree version release dates
# returns true if target version release date is less than (before) source version
def is_mapping_backwards(source_oncotree_version, target_oncotree_version):
    mapping_backwards_bool = False
    mapping_direction = "forward"
    response = requests.get(ONCOTREE_VERSION_ENDPOINT)
    if response.status_code != 200:
        print >> sys.stderr, "ERROR (HttpStatusCode %d): Unable to retrieve oncotree versions." % (response.status_code)
        sys.exit(1)
    for version in response.json():
        if version[VERSION_API_IDENTIFIER_FIELD] == source_oncotree_version:
            source_oncotree_version_release_date = version[VERSION_RELEASE_DATE_FIELD]
        if version[VERSION_API_IDENTIFIER_FIELD] == target_oncotree_version:
            target_oncotree_version_release_date = version[VERSION_RELEASE_DATE_FIELD]
    mapping_backwards_bool = target_oncotree_version_release_date < source_oncotree_version_release_date
    if mapping_backwards_bool:
        mapping_direction = "backward"
    print >> sys.stdout, "LOG: Based on provided versions (source: %s, target %s), tool will be run in %s direction" % (source_oncotree_version, target_oncotree_version, mapping_direction) 
    return target_oncotree_version_release_date < source_oncotree_version_release_date

#--------------------------------------------------------------
def load_oncotree_version(oncotree_version_name):
    oncotree_nodes = {}
    response = requests.get(ONCOTREE_TUMORTYPES_ENDPOINT + "?version=" + oncotree_version_name)
    if response.status_code != 200:
        print >> sys.stderr, "ERROR (HttpStatusCode %d): Unable to retrieve oncotree version %s." % (response.status_code, oncotree_version_name)
        sys.exit(1)
    for json_oncotree_node in response.json():
        new_node = {}
        new_node["parent"] = json_oncotree_node["parent"]
        new_node["precursors"] = json_oncotree_node["precursors"]
        new_node["revocations"] = json_oncotree_node["revocations"]
        new_node["history"] = json_oncotree_node["history"]
        new_node["code"] = json_oncotree_node["code"]
        oncotree_nodes[json_oncotree_node["code"]] = new_node
    return oncotree_nodes
#--------------------------------------------------------------
def get_header(file):
    header = []
    with open(file, "r") as header_source:
        for line in header_source:
            if not line.startswith("#"):
                header = line.rstrip().split('\t')
                break
    return header
#--------------------------------------------------------------
def load_input_file(input_file):
    header = get_header(input_file)
    headers_processed = False
    input_file_mapped_list = []

    with open(input_file) as data_file:
        for line in data_file.readlines():
            if line.startswith(METADATA_HEADER_PREFIX) or len(line.rstrip()) == 0:
                continue
            if not headers_processed:
                headers_processed = True
                continue
            data = dict(zip(header, map(str.strip, line.split('\t')))) 
            input_file_mapped_list.append(data)
    return input_file_mapped_list, header
#--------------------------------------------------------------
def translate_oncotree_codes(input_file_mapped_list, source_oncotree, target_oncotree, mapping_backwards, auto_mapping_enabled):
    for record in input_file_mapped_list:
        source_oncotree_code = record["ONCOTREE_CODE"]
        record["ONCOTREE_CODE"] = convert_to_target_oncotree_code(source_oncotree_code, source_oncotree, target_oncotree, mapping_backwards, auto_mapping_enabled)
    return input_file_mapped_list 

#--------------------------------------------------------------
def convert_to_target_oncotree_code(source_oncotree_code, source_oncotree, target_oncotree, mapping_backwards, auto_mapping_enabled):
    if source_oncotree_code in ["N/A", "", "NA"]:
        return source_oncotree_code
    if source_oncotree_code not in source_oncotree:
        print >> sys.stderr, "ERROR: Oncotree code (%s) can not be found in source oncotree. Please verify source version." % (source_oncotree_code)
        return source_oncotree_code
        sys.exit(1)
    source_oncotree_node = source_oncotree[source_oncotree_code]
    # get a set of possible codes that source code has been mapped to
    possible_target_oncotree_codes = get_possible_target_oncotree_nodes(source_oncotree_node, target_oncotree, is_backwards_mapping_bool)
    # resolve set of codes (cannot use possible_target_oncotree_nodes anymore)
    target_oncotree_code = resolve_possible_target_oncotree_codes(source_oncotree_code, possible_target_oncotree_nodes, source_oncotree, target_oncotree, auto_mapping_enabled)
    return target_oncotree_code

#--------------------------------------------------------------
# given a single oncotree node and mapping direction - return a set with possible mapped codes
def get_possible_target_oncotree_nodes(source_oncotree_node, target_oncotree, mapping_backwards):
    possible_target_oncotree_codes = set()
    source_oncotree_code = source_oncotree_node["code"]
    if mapping_backwards:        
        # Backwards mapping
        # codes in history is in the target version (Same URI - different name)
        possible_target_oncotree_codes.update(get_past_oncotree_codes_for_related_codes(source_oncotree_node, target_oncotree, "history"))
        if not possible_target_oncotree_codes: # history overrides current code when history is present (e.g PTCLNOS)
            if source_oncotree_code in target_oncotree:
                possible_target_oncotree_codes.add(source_oncotree_code)
        # codes in precusors is in the target version
        possible_target_oncotree_codes.update(get_past_oncotree_codes_for_related_codes(source_oncotree_node, target_oncotree, "precursors"))
        # skip checking codes in revocations - invalid codes which should not be considered 
        return possible_target_oncotree_codes
    else:
        # Forwards mapping
        # codes where source code is in history (this should at most be 1 node - because its the same URI)
        future_codes = get_future_related_oncotree_codes_for_source_code(source_oncotree_code, target_oncotree, "history")
        if len(future_codes) > 1:
            print >> sys.stderr, "ERROR: Future oncotree has multiple codes with code %s in history" % (source_oncotree_code)
            sys.exit(1)
        if len(future_codes) == 1:
            possible_target_oncotree_codes.update(future_codes)
            return possible_target_oncotree_codes
        # codes where source code is in precursor (this can be more than 1, but can not intersect with revocations)
        possible_target_oncotree_codes.update(get_future_related_oncotree_codes_for_source_code(source_oncotree_code, target_oncotree, "precursor"))
        if len(possible_target_oncotree_codes) > 0:
            return possible_target_oncotree_codes
        # codes where source code is in revocations (this can be more than 1) 
        possible_target_oncotree_codes.update(get_future_related_oncotree_codes_for_source_code(source_oncotree_code, target_oncotree, "revocations"))
        if len(possible_target_oncotree_codes) > 0:
            return possible_target_oncotree_codes
        # at this point, no matches - check if source code exists in future oncotree
        if source_oncotree_code in target_oncotree:
            possible_target_oncotree_codes.add(source_oncotree_code)
        return possible_target_oncotree_codes

#--------------------------------------------------------------
# exclusively for mapping in backward direction
# looking through 'related nodes (history, precursors)', return if found in target (past) oncotree
# i.e SLLCLL (SLL precusor, CLL precursor) -> SLL, CLL
def get_past_oncotree_codes_for_related_codes(source_oncotree_node, target_oncotree, field):
    return [past_oncotree_code for past_oncotree_code in source_oncotree_node[field] if past_oncotree_code in target_oncotree]

#--------------------------------------------------------------
# exclusively for mapping in forward direction
# returns codes where source code is related in target (future) oncotree
# i.e ALL -> BLL (ALL revocation), TLL (ALL revocation)
def get_future_related_oncotree_codes_for_source_code(source_oncotree_code, target_oncotree, field):
    return [future_oncotree_code for future_oncotree_code, future_oncotree_node in target_oncotree.items() if source_oncotree_code in future_oncotree_node[field]]

#--------------------------------------------------------------
# return a single string given a set of possible target oncotree codes
# return string format/content dependent on whether auto mapping is enabled (single code, list of codes, etc.)
# resolves issues such as no direct mappings and multiple possible mappings
def resolve_possible_target_oncotree_codes(source_oncotree_code, possible_target_oncotree_codes, source_oncotree, target_oncotree, auto_mapping_enabled):
    if len(possible_target_oncotree_codes) == 1:
        return possible_target_oncotree_codes.pop()
    if not auto_mapping_enabled:
        if len(possible_target_oncotree_codes) == 0:
            return "Oncotree Code (%s) needs to be manually mapped" % source_oncotree_code
        return "Choose from: " + ", ".join(possible_target_oncotree_codes)
    return "Complex algorithm incoming"

#--------------------------------------------------------------
def write_to_output_file(translated_input_file_mapped_list, output_file, header):
    with open(output_file, "w") as f:
        f.write('\t'.join(header) + "\n")
        for record in translated_input_file_mapped_list:
            formatted_data = map(lambda x: record.get(x,''), header)
            f.write('\t'.join(formatted_data) + '\n')

#--------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--auto-mapping-enabled", help = "enable automatic resolution of ambiguous mappings", action = "store_true")
    parser.add_argument("-i", "--input-file", help = "source file provided by user", required = True)
    parser.add_argument("-o", "--output-file", help = "destination file to write out new file contents", required = True)
    parser.add_argument("-s", "--source-version", help = "current oncotree version used in the source file", required = True)
    parser.add_argument("-t", "--target-version", help = "oncotree version to be mapped to in the destination file", required = True)
    args = parser.parse_args()

    auto_mapping_enabled = args.auto_mapping_enabled
    input_file = args.input_file
    output_file = args.output_file
    source_version = args.source_version
    target_version = args.target_version    

    if not os.path.isfile(input_file):
        print >> sys.stderr, "Error: Input file (%s) can not be found" % (input_file)
        sys.exit(1)
    if not oncotree_version_exists(source_version):
        print >> sys.stderr, "ERROR: Source version (%s) is not a valid oncotree version" % (source_version)
        sys.exit(1)
    if not oncotree_version_exists(target_version):
        print >> sys.stderr, "ERROR: Target version (%s) is not a valid oncotree version" % (target_version) 
        sys.exit(1)

    mapping_backwards = is_mapping_backwards(source_version, target_version)
    input_file_mapped_list, header = load_input_file(input_file)
    source_oncotree = load_oncotree_version(source_version)
    target_oncotree = load_oncotree_version(target_version)
    translated_input_file_mapped_list = translate_oncotree_codes(input_file_mapped_list, source_oncotree, target_oncotree, mapping_backwards, auto_mapping_enabled)
    write_to_output_file(translated_input_file_mapped_list, output_file, header)

if __name__ == '__main__':
   main() 
