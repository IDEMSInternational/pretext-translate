import os
import subprocess
import json
import deepl
import shutil
import xml.etree.ElementTree as ET

# Standard XML namespaces
NAMESPACES = {
    'xlf': 'urn:oasis:names:tc:xliff:document:1.2',
    'tmx': 'http://www.lisa.org/tmx14'
}
# Register the default namespace so ET doesn't prepend 'ns0:' to every tag
ET.register_namespace('', NAMESPACES['xlf'])
ET.register_namespace('tmx', NAMESPACES['tmx'])

class PretextTranslationPipeline:
    def __init__(self, config):
        self.config = config
        self.tikal_cmd = config.get('tikal_path', 'tikal') # Configurable Tikal path
        self.merged_xlf_path = config.get('merged_xliff_file', 'merged_project.xlf')
        self.deepl_url = "https://api-free.deepl.com/v2/translate" 
        
        # Load or initialize the Translation Memory (TMX)
        self.tm_path = config.get('tmx_file', 'project_memory.tmx')
        self.tm_tree, self.tm_root = self._init_tmx()
        self.memory_cache = self._load_tm_into_dict()

    def run_pipeline(self):
        """Executes the full extraction, translation, and merge pipeline."""
        print("Starting Localization Pipeline...")
        
        # Build the full list of files dynamically via recursive xi:include parsing
        source_files = [os.path.join(self.config['project_root'], source_file) for source_file in self.config['source_files']]
        all_source_files = self._discover_source_files(source_files)
        print(f"Found {len(all_source_files)} total PreTeXt files to process.")
        
        # 1. Extract individual XLIFFs
        individual_xlfs = []
        for source_file in all_source_files:
            xlf = self._extract_xliff(source_file)
            if xlf: individual_xlfs.append(xlf)

        # 2. Combine them into a single master XLIFF
        self._combine_xliffs(individual_xlfs, self.merged_xlf_path)
        
        # # 3. Translate the single master XLIFF
        self._translate_xliff(self.merged_xlf_path)
        
        # # 4. Split the translated master XLIFF back into individual files
        self._split_xliffs(self.merged_xlf_path, individual_xlfs)
        
        # # 5. Merge the translated strings back into the target XML formats
        for xlf in individual_xlfs:
            self._merge_xliff(xlf)

        # 6: Build the clean output directory!
        root_dir = self.config['project_root']
        self._build_target_tree(root_dir)
        
        print("\nPipeline completed successfully.")

    def _discover_source_files(self, entry_files):
        """Recursively parses XML files to find all xi:includes and build a complete file list."""
        print("Scanning PreTeXt tree for included files...")
        discovered = set()
        files_to_scan = list(entry_files)
        xi_ns = 'http://www.w3.org/2001/XInclude'
        
        while files_to_scan:
            current_file = files_to_scan.pop(0)
            abs_path = os.path.abspath(current_file)
            
            if abs_path in discovered:
                continue
                
            discovered.add(abs_path)
            
            try:
                tree = ET.parse(abs_path)
                root = tree.getroot()
                base_dir = os.path.dirname(abs_path)
                
                # Find all <xi:include href="..."> tags
                for include_node in root.findall(f'.//{{{xi_ns}}}include'):
                    href = include_node.get('href')
                    if href:
                        # PreTeXt paths are relative to the file doing the including
                        included_file = os.path.normpath(os.path.join(base_dir, href))
                        if os.path.exists(included_file):
                            files_to_scan.append(included_file)
                        else:
                            print(f"  Warning: Included file not found: {included_file}")
            except Exception as e:
                print(f"  Warning: Could not parse {current_file} for includes. Error: {e}")
                
        return list(discovered)

    # --- 1. OKAPI EXTRACTION ---
    def _extract_xliff(self, source_file):
        """Uses Okapi Tikal to extract text into an XLIFF file."""
        print(f"Extracting strings from {source_file}...")
        cmd = [
            self.tikal_cmd,
            '-x', source_file,
            '-sl', self.config['source_lang'],
            '-tl', self.config['target_lang'],
            '-fc', self.config['filter_config']
        ]
        
        if self.config.get('segmentation_srx'):
            cmd.extend(['-seg', self.config['segmentation_srx']])
            
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return f"{source_file}.xlf"
        except subprocess.CalledProcessError as e:
            self._print_error(cmd, e)
            return None

    # --- 2. XLIFF COMBINATION & SPLITTING ---
    def _combine_xliffs(self, xlf_files, output_path):
        """Merges multiple XLIFF files into a single master XLIFF 1.2 document."""
        print(f"Combining {len(xlf_files)} files into {output_path}...")
        master_tree = ET.Element('xliff', {'version': '1.2'})
        
        for xlf in xlf_files:
            tree = ET.parse(xlf)
            root = tree.getroot()
            # XLIFF 1.2 holds document data in <file> blocks. We append each file block to the master.
            for file_node in root.findall('xlf:file', NAMESPACES):
                master_tree.append(file_node)
                
        ET.ElementTree(master_tree).write(output_path, encoding='utf-8', xml_declaration=True)

    def _split_xliffs(self, merged_path, target_xlf_files):
        """Splits a master XLIFF back out into individual files safely using basenames."""
        print(f"Splitting {merged_path} back into individual files for Okapi...")
        tree = ET.parse(merged_path)
        root = tree.getroot()
        xlf_ns = NAMESPACES['xlf']
        
        # Create a dictionary mapping the base filename back to its absolute path
        xlf_map = {os.path.basename(f): f for f in target_xlf_files}
        
        for file_node in root.findall(f'.//{{{xlf_ns}}}file') or root.findall('.//file'):
            original_source = file_node.get('original')
            expected_basename = f"{os.path.basename(original_source)}.xlf"
            
            # Now it matches flawlessly!
            if expected_basename in xlf_map:
                out_path = xlf_map[expected_basename]
                
                # Reconstruct the XLIFF envelope with the proper namespace
                single_tree = ET.Element(f'{{{xlf_ns}}}xliff', {'version': '1.2'})
                single_tree.append(file_node)
                ET.ElementTree(single_tree).write(out_path, encoding='utf-8', xml_declaration=True)

    # --- 3. XLIFF PROCESSING & DEEPL TRANSLATION ---
    def _translate_xliff(self, xliff_file):
        """Parses XLIFF, checks TM, batches missing segments to DeepL, and saves XLIFF."""
        
        print(f"Processing translations for {xliff_file}...")
        tree = ET.parse(xliff_file)
        root = tree.getroot()
        updates_made = False

        # 1. Collect all unique strings that are missing from the Translation Memory
        strings_to_translate = []
        trans_units = root.findall('.//xlf:trans-unit', NAMESPACES)

        for trans_unit in trans_units:
            source_el = trans_unit.find('xlf:source', NAMESPACES)
            if source_el is None:
                continue
            source_xml_str = self._inner_xml(source_el)           
            # Now check if the compiled string is actually empty
            if not source_xml_str.strip():
                continue
            
            # Queue for translation if not in cache and not already queued
            if source_xml_str not in self.memory_cache and source_xml_str not in strings_to_translate:
                strings_to_translate.append(source_xml_str)

        # 2. Batch Translate with DeepL
        print(f"Sending {len(strings_to_translate)} segments to DeepL in batch mode...")
        if strings_to_translate:
            translator = deepl.Translator(self.config['deepl_api_key'])

            # Safely process the strings in limits-compliant batches
            for batch in self._chunk_for_deepl(strings_to_translate):
                try:
                    # The translate_text function accepts a list of strings for batching
                    results = translator.translate_text(
                        batch,
                        source_lang=self.config['source_lang'][:2].upper(),
                        target_lang=self.config['target_lang'][:2].upper(),
                        tag_handling="xml",
                        ignore_tags=["bpt", "ept", "ph", "it", "x", "bx", "ex"],
                        # 2. Translate the content of these, but don't break the sentence
                        non_splitting_tags=["g", "mrk", "sub"]
                    )
                    
                    # DeepL returns a single object if only one string was sent, 
                    # so we normalize it into a list for consistent iteration.
                    if not isinstance(results, list):
                        results = [results]
                        
                    # Update our local memory cache and the TMX database
                    for source_str, result in zip(batch, results):
                        translated_str = result.text
                        self._add_to_tmx(source_str, translated_str)
                        self.memory_cache[source_str] = translated_str
                        updates_made = True
                        
                except deepl.DeepLException as e:
                    print(f"❌ DeepL API Error during batch translation: {e}")
                    # The script will continue and apply whatever is already in the TM cache

        # 3. Inject translations (both from TM and new DeepL results) back into the XLIFF
        for trans_unit in trans_units:
            source_el = trans_unit.find('xlf:source', NAMESPACES)
            target_el = trans_unit.find('xlf:target', NAMESPACES)
            
            if source_el is None or not source_el.text:
                continue

            source_xml_str = self._inner_xml(source_el)
            
            if source_xml_str in self.memory_cache:
                self._inject_translation(target_el, self.memory_cache[source_xml_str])
                updates_made = True

        # 4. Save the updated files
        if updates_made:
            tree.write(xliff_file, encoding='utf-8', xml_declaration=True)
            self.tm_tree.write(self.tm_path, encoding='utf-8', xml_declaration=True)

    def _chunk_for_deepl(self, strings, max_strings=50, max_chars=30000):
        """Yields safe batches of strings that strictly obey DeepL API limits."""
        current_batch = []
        current_chars = 0
        
        for string in strings:
            # If adding the next string exceeds the API limits, yield the current batch
            if len(current_batch) >= max_strings or (current_chars + len(string)) > max_chars:
                if current_batch:
                    yield current_batch
                current_batch = []
                current_chars = 0
                
            current_batch.append(string)
            current_chars += len(string)
            
        # Yield any remaining strings in the final batch
        if current_batch:
            yield current_batch

    def _inject_translation(self, target_el, translated_str):
        """Safely clears existing target content and inserts the translated string."""
        # 1. Completely clear existing text and children (which Okapi pre-fills with English)
        target_el.text = None
        for child in list(target_el):
            target_el.remove(child)
            
        # 2. Inject the translated text
        target_el.insert(0, ET.fromstring(f"<wrapper>{translated_str}</wrapper>"))
        self._flatten_wrapper(target_el)

    # --- 4. OKAPI MERGE ---
    def _merge_xliff(self, xliff_file):
        """Uses Okapi Tikal to merge the translated individual XLIFF back into the target format."""
        print(f"Merging translations back into source format for {xliff_file}...")
        cmd = [
            self.tikal_cmd,
            '-m', xliff_file,
            '-sl', self.config['source_lang'],
            '-tl', self.config['target_lang'],
            '-fc', self.config['filter_config']
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            self._print_error(cmd, e)

    def _build_target_tree(self, project_root):
        """
        Creates a deep copy of the project root and replaces original XML/PTX files
        with their translated Okapi outputs, yielding a ready-to-compile project.
        """
        print(f"\nBuilding final translated project tree from: {project_root}")
        
        # Ensure we have an absolute path, and define the target folder name
        abs_root = os.path.abspath(project_root)
        target_dir = f"{abs_root}_translated_{self.config['target_lang']}"
        
        # 1. Create a fresh deep copy of the entire project
        if os.path.exists(target_dir):
            print(f"  Removing existing target directory: {target_dir}")
            shutil.rmtree(target_dir)
            
        print(f"  Cloning project to: {target_dir}")
        shutil.copytree(abs_root, target_dir)
        
        # 2. Walk the cloned tree to perform the swaps and cleanup
        for dirpath, _, files in os.walk(target_dir):
            for filename in files:
                filepath = os.path.join(dirpath, filename)
                
                # Clean up the Okapi XLIFF extraction artifacts
                if filename.endswith('.xlf'):
                    os.remove(filepath)
                    continue
                    
                # Find Okapi output files and overwrite the originals
                if filename.endswith('.out.ptx') or filename.endswith('.out.xml'):
                    # e.g., 'chapter1.out.ptx' -> 'chapter1.ptx'
                    original_name = filename.replace('.out.ptx', '.ptx').replace('.out.xml', '.xml')
                    original_filepath = os.path.join(dirpath, original_name)
                    
                    # Overwrite the original English file with the translated Okapi file
                    shutil.move(filepath, original_filepath)
                    
        print(f"✅ Translated project successfully built and ready to compile at: {target_dir}")

    # --- HELPER FUNCTIONS ---
    def _inner_xml(self, element):
        return (element.text or '') + ''.join(ET.tostring(e, encoding='unicode') for e in element)

    def _flatten_wrapper(self, target_el):
        wrapper = target_el.find('wrapper')
        if wrapper is not None:
            target_el.text = wrapper.text
            for child in list(wrapper): target_el.append(child)
            target_el.remove(wrapper)

    def _print_error(self, cmd, e):
        print("\n" + "="*40 + "\n❌ TIKAL CRASHED!\n" + "="*40)
        print(f"Command executed: {' '.join(cmd)}")
        print(f"Exit Code: {e.returncode}")
        print("\n--- TIKAL ERROR OUTPUT (STDERR) ---\n" + e.stderr)
        print("="*40 + "\n")
        raise

    # --- TRANSLATION MEMORY (TMX) MANAGEMENT ---
    def _init_tmx(self):
        if os.path.exists(self.tm_path):
            tree = ET.parse(self.tm_path)
            return tree, tree.getroot()
        
        # Explicitly apply the namespace when creating a new file
        tmx_ns = NAMESPACES['tmx']
        root = ET.Element(f'{{{tmx_ns}}}tmx', {'version': '1.4'})
        ET.SubElement(root, f'{{{tmx_ns}}}header', {
            'creationtool': 'PretextTranslator', 
            'datatype': 'xml', 
            'segtype': 'paragraph', 
            'adminlang': 'en', 
            'srclang': self.config['source_lang']
        })
        ET.SubElement(root, f'{{{tmx_ns}}}body')
        return ET.ElementTree(root), root

    def _load_tm_into_dict(self):
        cache = {}
        
        # 1. Safely find the body tag regardless of its namespace prefix
        body = None
        for elem in self.tm_root.iter():
            if elem.tag.endswith('body'):
                body = elem
                break
                
        if body is None: return cache

        # 2. Iterate through all children of the body
        for tu in body:
            if not tu.tag.endswith('tu'): continue
            
            src_str = tgt_str = None
            for tuv in tu:
                if not tuv.tag.endswith('tuv'): continue
                
                # Safely extract the language attribute ignoring namespace prefixes
                lang = None
                for k, v in tuv.attrib.items():
                    if k.endswith('lang'):
                        lang = v.lower()
                        break
                        
                if not lang: continue
                
                # Safely find the seg tag
                seg = None
                for child in tuv:
                    if child.tag.endswith('seg'):
                        seg = child
                        break
                        
                # Extract and map the text
                if seg is not None:
                    inner_str = self._inner_xml(seg)
                    
                    if lang.startswith(self.config['source_lang'].lower()): 
                        src_str = inner_str
                    if lang.startswith(self.config['target_lang'].lower()): 
                        tgt_str = inner_str
            
            # If we found both, add to the dictionary
            if src_str and tgt_str:
                cache[src_str] = tgt_str
                
        return cache

    def _add_to_tmx(self, source_text, target_text):
        tmx_ns = NAMESPACES['tmx']
        xml_ns = '{http://www.w3.org/XML/1998/namespace}'
        
        body = self.tm_root.find('tmx:body', NAMESPACES)
        if body is None:
            body = self.tm_root.find('body')
            
        tu = ET.SubElement(body, f'{{{tmx_ns}}}tu', {'creationid': 'DeepL_API', 'creationdate': 'auto'})
        
        for lang, text in [(self.config['source_lang'], source_text), (self.config['target_lang'], target_text)]:
            # Safely write the language attribute using the fully qualified W3C namespace
            tuv = ET.SubElement(tu, f'{{{tmx_ns}}}tuv', {f'{xml_ns}lang': lang})
            seg = ET.SubElement(tuv, f'{{{tmx_ns}}}seg')
            seg.insert(0, ET.fromstring(f"<wrapper>{text}</wrapper>"))
            self._flatten_wrapper(seg)

def load_auth_key(filename):
    data = json.load(open(filename))
    return data["auth_key"]


# ==========================================
# CONFIGURATION & EXECUTION
# ==========================================
if __name__ == "__main__":
    pipeline_config = {
        # Okapi Configurations
        'filter_config': 'okf_xml@pretext_settings.fprm',
        'tmx_file': 'project_memory.tmx',
        # Master Output XLIFF (Where the extracted strings merge)
        'merged_xliff_file': 'merged_translation_project.xlf',
        # (Optional) Path to SRX segmentation rules. Leave empty for ITS-only paragraph segmentation.
        # 'segmentation_srx': 'paragraph_segmentation.srx',

        # Tikal Executable Path
        # Can be an absolute path (e.g., '/opt/okapi/tikal.sh') or just 'tikal' if in PATH
        'tikal_path': 'tikal',
        
        # Project-specific config
        # Source Files to Process
        'project_root': 'minimal',
        'source_files': ['source/main.ptx'],
        # 'project_root': 'showcase',
        # 'source_files': ['source/pretext-showcase.ptx'],
        # Languages & APIs
        'source_lang': 'en',
        'target_lang': 'fr',
        'deepl_api_key': load_auth_key("auth_key.json"),
    }

    pipeline = PretextTranslationPipeline(pipeline_config)
    pipeline.run_pipeline()
