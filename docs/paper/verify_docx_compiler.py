import zipfile
import lxml.etree as ET
import re

NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'
}

def audit_docx(docx_path):
    print(f"\n================ AUDITING {docx_path} ================")
    with zipfile.ZipFile(docx_path) as z:
        doc_xml = z.read('word/document.xml')
        root = ET.fromstring(doc_xml)
        
        # 1. Formula audit
        math_nodes = root.xpath('//m:oMath', namespaces=NS)
        math_para_nodes = root.xpath('//m:oMathPara', namespaces=NS)
        e_nodes = root.xpath('//m:e', namespaces=NS)
        empty_e_nodes = []
        for e in e_nodes:
            if len(e) == 0 and not (e.text and e.text.strip()):
                parent = e.getparent()
                empty_e_nodes.append((parent.tag if parent is not None else 'unknown', ET.tostring(parent).decode('utf-8')[:100]))
                
        print(f"[+] Total Math Formulas (<m:oMath>): {len(math_nodes)}")
        print(f"[+] Total Display Math Blocks (<m:oMathPara>): {len(math_para_nodes)}")
        print(f"[+] Total Element Containers (<m:e>): {len(e_nodes)}")
        print(f"[+] Empty Placeholder Containers (dashed boxes): {len(empty_e_nodes)}")
        if empty_e_nodes:
            print("  [!] WARNING: Empty <m:e> detected:")
            for ptag, snippet in empty_e_nodes[:5]:
                print(f"      Parent: {ptag} -> {snippet}")
            assert False, "Empty <m:e> found!"
        else:
            print("  [✓] ZERO empty <m:e> tags! Absolutely NO dashed boxes in formulas!")

        # 2. Images audit
        media_files = [f for f in z.namelist() if f.startswith('word/media/')]
        print(f"[+] Total Embedded Images: {len(media_files)}")
        for mf in sorted(media_files):
            print(f"      - {mf} ({z.getinfo(mf).file_size} bytes)")
        assert len(media_files) == 8, f"Expected 8 images, found {len(media_files)}"

        # 3. Tables audit
        tbl_nodes = root.xpath('//w:tbl', namespaces=NS)
        print(f"[+] Total Tables in Document: {len(tbl_nodes)} (7 empirical tables + 4 callout boxes + 2 code listings = 13 table elements)")
        
        # 4. Text content & Forbidden terms audit
        w_text = ''.join(root.xpath('//w:t/text()', namespaces=NS))
        m_text = ''.join(root.xpath('//m:t/text()', namespaces=NS))
        all_text = w_text + " " + m_text
        print(f"[+] Total Text Characters: {len(all_text)} (Body Text: {len(w_text)}, Math Text: {len(m_text)})")
        
        forbidden = [
            '石井', 'Ishii', '2024YFB', '624XXXX', '系统软件与智能安全实验室',
            '审稿人防御性注记', '学术严谨性注记', '为回答审稿人关于',
            'reviewer scrutiny', 'Academic Rigor Note', 'defensive note'
        ]
        violations = []
        for fb in forbidden:
            if fb.lower() in all_text.lower():
                violations.append(fb)
                
        if violations:
            print(f"[!] FAILED: Found forbidden terms: {violations}")
            assert False, f"Found forbidden terms: {violations}"
        else:
            print("  [✓] ZERO forbidden terms, ZERO defensive reviewer notes found!")

        # 5. Theoretical advances keywords audit
        is_en = 'en' in docx_path.lower() or docx_path.endswith('beyond_surface_adaptation.docx')
        author_kw = 'Hanqin Yang' if is_en else '杨涵钦'
        required_keywords = [
            'DSDA', author_kw, 'Anderson', 'Rice', '0.00%'
        ]
        for kw in required_keywords:
            found = kw in all_text
            print(f"      Keyword '{kw}': {'FOUND' if found else 'MISSING'}")
            assert found, f"Required keyword '{kw}' missing!"

        print(f"[SUCCESS] {docx_path} PASSED ALL ACADEMIC AUDITS!")

if __name__ == '__main__':
    audit_docx('docs/paper/beyond_surface_adaptation_zh.docx')
    audit_docx('docs/paper/beyond_surface_adaptation.docx')
