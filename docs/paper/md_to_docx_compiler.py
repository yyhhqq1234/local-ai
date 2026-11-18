"""md_to_docx_compiler.py · Industrial Markdown-to-DOCX Academic Compiler (v2.0).
Directly compiles Markdown paper files into high-standard DOCX papers:
- Math-First Tokenizer: Protects math ($$...$$ and $...$) before bold/italic to prevent superscript asterisk corruption (e.g. y^*).
- Full Mathematical Fidelity: Converts formulas via latex2mathml + MML2OMML.XSL + clean_omml (0 empty <m:e> tags, 0 dashed boxes).
- Multi-block Callout Boxes: Blockquotes (Theorems, Propositions, Corollaries) support native centered display math and distinct paragraphs.
- Zero Caption Duplication: Suppresses redundant alt-attribute captions and filters out foreign subtitle lines in Chinese paper.
- Academic 3-line tables with header shading and DSDA blue accenting.
- Embedded figures from images/ with centered bold captions.
"""

import os
import re
import sys
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
import lxml.etree as ET
import latex2mathml.converter

# ---------------------------------------------------------
# OMML Math Conversion Setup
# ---------------------------------------------------------
XSLT_PATH = r'C:\Program Files\Microsoft Office\root\Office16\MML2OMML.XSL'
_xslt_transform = None

def get_omml_transform():
    global _xslt_transform
    if _xslt_transform is None and os.path.exists(XSLT_PATH):
        try:
            xslt_doc = ET.parse(XSLT_PATH)
            _xslt_transform = ET.XSLT(xslt_doc)
        except Exception as e:
            print(f"[!] Warning: Could not load MML2OMML.XSL: {e}")
    return _xslt_transform

NS = {'m': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}

def clean_omml(root):
    """
    Eliminates dotted empty placeholder boxes in OMML by transforming:
    1. Empty m:nary operators into clean m:sSub / m:sSubSup / m:sSup
    2. Empty m:e bases in scripts into empty text runs or removing them
    """
    for nary in root.xpath('//m:nary', namespaces=NS):
        e = nary.find('m:e', namespaces=NS)
        if e is not None and len(e) == 0 and not (e.text and e.text.strip()):
            sub = nary.find('m:sub', namespaces=NS)
            sup = nary.find('m:sup', namespaces=NS)
            naryPr = nary.find('m:naryPr', namespaces=NS)
            chr_val = '∑'
            if naryPr is not None:
                chr_elem = naryPr.find('m:chr', namespaces=NS)
                if chr_elem is not None:
                    chr_val = chr_elem.get('{http://schemas.openxmlformats.org/officeDocument/2006/math}val', '∑')
            
            has_sub = sub is not None and (len(sub) > 0 or (sub.text and sub.text.strip()))
            has_sup = sup is not None and (len(sup) > 0 or (sup.text and sup.text.strip()))
            
            parent = nary.getparent()
            if parent is None:
                continue
            if has_sub and has_sup:
                new_elem = ET.Element('{http://schemas.openxmlformats.org/officeDocument/2006/math}sSubSup')
                base_e = ET.SubElement(new_elem, '{http://schemas.openxmlformats.org/officeDocument/2006/math}e')
                r = ET.SubElement(base_e, '{http://schemas.openxmlformats.org/officeDocument/2006/math}r')
                t = ET.SubElement(r, '{http://schemas.openxmlformats.org/officeDocument/2006/math}t')
                t.text = chr_val
                new_elem.append(sub)
                new_elem.append(sup)
                parent.replace(nary, new_elem)
            elif has_sub:
                new_elem = ET.Element('{http://schemas.openxmlformats.org/officeDocument/2006/math}sSub')
                base_e = ET.SubElement(new_elem, '{http://schemas.openxmlformats.org/officeDocument/2006/math}e')
                r = ET.SubElement(base_e, '{http://schemas.openxmlformats.org/officeDocument/2006/math}r')
                t = ET.SubElement(r, '{http://schemas.openxmlformats.org/officeDocument/2006/math}t')
                t.text = chr_val
                new_elem.append(sub)
                parent.replace(nary, new_elem)
            elif has_sup:
                new_elem = ET.Element('{http://schemas.openxmlformats.org/officeDocument/2006/math}sSup')
                base_e = ET.SubElement(new_elem, '{http://schemas.openxmlformats.org/officeDocument/2006/math}e')
                r = ET.SubElement(base_e, '{http://schemas.openxmlformats.org/officeDocument/2006/math}r')
                t = ET.SubElement(r, '{http://schemas.openxmlformats.org/officeDocument/2006/math}t')
                t.text = chr_val
                new_elem.append(sup)
                parent.replace(nary, new_elem)

    # 2. Fix empty base elements in m:sSup / m:sSub / m:sSubSup to eliminate dashed boxes
    for script in root.xpath('//m:sSup | //m:sSub | //m:sSubSup', namespaces=NS):
        base_e = script.find('m:e', namespaces=NS)
        if base_e is not None and len(base_e) == 0 and not (base_e.text and base_e.text.strip()):
            r = ET.SubElement(base_e, '{http://schemas.openxmlformats.org/officeDocument/2006/math}r')
            t = ET.SubElement(r, '{http://schemas.openxmlformats.org/officeDocument/2006/math}t')
            t.text = ''

def latex_to_omml_element(latex_str, is_display=False):
    """Converts a LaTeX formula string to a parsed docx OMML XML element."""
    transform = get_omml_transform()
    if transform is None:
        return None
    try:
        clean_latex = latex_str.strip()
        clean_latex = clean_latex.replace(r'\operatorname{argmax}', r'\arg\max')
        clean_latex = clean_latex.replace(r'\operatorname{argmin}', r'\arg\min')
        clean_latex = clean_latex.replace(r'\operatorname{diag}', r'\text{diag}')
        clean_latex = clean_latex.replace(r'\operatorname{span}', r'\text{span}')
        clean_latex = clean_latex.replace(r'\operatorname{col}', r'\text{col}')
        clean_latex = clean_latex.replace(r'\operatorname{Tr}', r'\text{Tr}')
        clean_latex = clean_latex.replace(r'\operatorname{Acc}', r'\text{Acc}')
        clean_latex = clean_latex.replace(r'\operatorname{ACE}', r'\text{ACE}')
        clean_latex = clean_latex.replace(r'\widehat{\operatorname{ACE}}', r'\widehat{\text{ACE}}')
        clean_latex = clean_latex.replace(r'\triangleq', r'\triangleq')
        clean_latex = clean_latex.replace(r'\text{geo}', r'\text{geo}')
        mml = latex2mathml.converter.convert(clean_latex)
        dom = ET.fromstring(mml)
        omml = transform(dom)
        root = omml.getroot()
        clean_omml(root)
        
        if is_display:
            omml_para = ET.Element('{http://schemas.openxmlformats.org/officeDocument/2006/math}oMathPara')
            omml_para.append(root)
            omml_str = ET.tostring(omml_para).decode('utf-8')
        else:
            omml_str = ET.tostring(root).decode('utf-8')
            
        return parse_xml(omml_str)
    except Exception as e:
        return None

# ---------------------------------------------------------
# Markdown Inline Lexer / Tokenizer (Math-First)
# ---------------------------------------------------------
def parse_inline(text):
    """
    Robust inline parser:
    1. Splits text by bold spans `**...**`
    2. Inside each span, splits by Math ($$...$$ and $...$) and Code (`...`)
    3. In remaining plain text, splits by Italic (*...*)
    This guarantees that asterisks inside math ($y^*$, $x^*$) can NEVER be hijacked by italic!
    """
    results = []
    parts = re.split(r'(\*\*.*?\*\*)', text)
    
    for part in parts:
        if not part:
            continue
        is_bold = part.startswith('**') and part.endswith('**') and len(part) >= 4
        content = part[2:-2] if is_bold else part
        
        # Split by Math ($$...$$ and $...$) and Code (`...`)
        sub_pattern = r'(\$\$.*?\$\$|(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)|`[^`]+`)'
        sub_parts = re.split(sub_pattern, content)
        
        for sp in sub_parts:
            if not sp:
                continue
            if sp.startswith('$$') and sp.endswith('$$'):
                results.append({
                    'type': 'display_math',
                    'content': sp[2:-2].strip(),
                    'bold': is_bold,
                    'italic': False
                })
            elif sp.startswith('$') and sp.endswith('$'):
                results.append({
                    'type': 'math',
                    'content': sp[1:-1].strip(),
                    'bold': is_bold,
                    'italic': False
                })
            elif sp.startswith('`') and sp.endswith('`'):
                results.append({
                    'type': 'code',
                    'content': sp[1:-1],
                    'bold': is_bold,
                    'italic': False
                })
            else:
                # Plain text: can contain italic *...*
                italic_parts = re.split(r'(\*[^*]+?\*)', sp)
                for ip in italic_parts:
                    if not ip:
                        continue
                    if ip.startswith('*') and ip.endswith('*') and len(ip) >= 2:
                        results.append({
                            'type': 'text',
                            'content': ip[1:-1],
                            'bold': is_bold,
                            'italic': True
                        })
                    else:
                        results.append({
                            'type': 'text',
                            'content': ip,
                            'bold': is_bold,
                            'italic': False
                        })
    return results

# ---------------------------------------------------------
# Blockquote Sub-block Parser
# ---------------------------------------------------------
def parse_blockquote_subblocks(content):
    """Parses blockquote content into distinct subblocks (paragraphs, display math, list items)."""
    lines = content.splitlines()
    subblocks = []
    i = 0
    n = len(lines)
    while i < n:
        l = lines[i].strip()
        if not l:
            i += 1
            continue
        if l.startswith('$$'):
            if l.endswith('$$') and len(l) > 2:
                subblocks.append({'type': 'display_math', 'content': l[2:-2].strip()})
                i += 1
            else:
                math_lines = []
                i += 1
                while i < n and not lines[i].strip().startswith('$$'):
                    math_lines.append(lines[i].strip())
                    i += 1
                i += 1
                subblocks.append({'type': 'display_math', 'content': '\n'.join(math_lines).strip()})
            continue
        list_match = re.match(r'^(\(\w+\)|\d+\.)\s+(.*)$', l)
        if list_match:
            subblocks.append({'type': 'list_item', 'bullet': list_match.group(1), 'text': list_match.group(2)})
            i += 1
            continue
        # Paragraph
        para_lines = [l]
        i += 1
        while i < n:
            nl = lines[i].strip()
            if not nl or nl.startswith('$$') or re.match(r'^(\(\w+\)|\d+\.)\s+', nl):
                break
            para_lines.append(nl)
            i += 1
        subblocks.append({'type': 'paragraph', 'text': ' '.join(para_lines)})
    return subblocks

# ---------------------------------------------------------
# Markdown Block Parser
# ---------------------------------------------------------
def parse_markdown_blocks(text):
    lines = text.splitlines()
    blocks = []
    i = 0
    n = len(lines)
    
    while i < n:
        line = lines[i]
        stripped = line.strip()
        
        # Blank line or raw HTML wrapper tags
        if (not stripped or 
            stripped.startswith('<p') or 
            stripped == '</p>' or 
            stripped.startswith('<div') or 
            stripped == '</div>'):
            i += 1
            continue
            
        # Code block
        if stripped.startswith('```'):
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1
            blocks.append({
                'type': 'code',
                'lang': lang,
                'content': '\n'.join(code_lines)
            })
            continue
            
        # Display math
        if stripped.startswith('$$'):
            if stripped.endswith('$$') and len(stripped) > 2:
                blocks.append({
                    'type': 'display_math',
                    'content': stripped[2:-2].strip()
                })
                i += 1
            else:
                math_lines = []
                i += 1
                while i < n and not lines[i].strip().startswith('$$'):
                    math_lines.append(lines[i])
                    i += 1
                i += 1
                blocks.append({
                    'type': 'display_math',
                    'content': '\n'.join(math_lines).strip()
                })
            continue
            
        # Horizontal rule
        if stripped == '---':
            blocks.append({'type': 'hr'})
            i += 1
            continue
            
        # Image tag
        img_match = re.search(r'<img\s+src="([^"]+)"(?:\s+alt="([^"]*)")?(?:\s+width="([^"]*)")?', stripped)
        if img_match:
            blocks.append({
                'type': 'image',
                'src': img_match.group(1),
                'alt': img_match.group(2) or '',
                'width': img_match.group(3) or ''
            })
            i += 1
            continue
            
        # Heading
        heading_match = re.match(r'^(#{1,4})\s+(.*)$', stripped)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            blocks.append({
                'type': 'heading',
                'level': level,
                'title': title
            })
            i += 1
            continue
            
        # Blockquote (Theorems, Propositions, Remarks, Axioms)
        if stripped.startswith('>'):
            quote_lines = []
            while i < n and lines[i].strip().startswith('>'):
                ql = lines[i].strip()
                if ql.startswith('> '):
                    quote_lines.append(ql[2:])
                elif ql.startswith('>'):
                    quote_lines.append(ql[1:])
                i += 1
            blocks.append({
                'type': 'blockquote',
                'content': '\n'.join(quote_lines).strip()
            })
            continue
            
        # Table
        if stripped.startswith('|'):
            table_lines = []
            while i < n and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            blocks.append({
                'type': 'table',
                'lines': table_lines
            })
            continue
            
        # List item
        list_match = re.match(r'^([-*]|\d+\.|\(\d+\))\s+(.*)$', stripped)
        if list_match:
            bullet_type = list_match.group(1)
            item_text = list_match.group(2).strip()
            i += 1
            while i < n:
                next_s = lines[i].strip()
                if not next_s:
                    break
                if (re.match(r'^([-*]|\d+\.|\(\d+\))\s+', next_s) or 
                    next_s.startswith('|') or next_s.startswith('#') or 
                    next_s.startswith('>') or next_s.startswith('$$') or 
                    next_s.startswith('```') or next_s == '---' or 
                    next_s.startswith('<img')):
                    break
                item_text += ' ' + next_s
                i += 1
            blocks.append({
                'type': 'list_item',
                'bullet': bullet_type,
                'text': item_text
            })
            continue
            
        # Paragraph
        para_lines = [stripped]
        i += 1
        while i < n:
            next_s = lines[i].strip()
            if not next_s:
                break
            if (re.match(r'^([-*]|\d+\.|\(\d+\))\s+', next_s) or 
                next_s.startswith('|') or next_s.startswith('#') or 
                next_s.startswith('>') or next_s.startswith('$$') or 
                next_s.startswith('```') or next_s == '---' or 
                next_s.startswith('<img')):
                break
            para_lines.append(next_s)
            i += 1
            
        blocks.append({
            'type': 'paragraph',
            'text': '\n'.join(para_lines)
        })
        
    return blocks

# ---------------------------------------------------------
# DOCX Generation Core
# ---------------------------------------------------------
def compile_md_to_docx(md_path, docx_path, is_zh=True):
    print(f"\n[+] Compiling {md_path} -> {docx_path} (Language: {'ZH' if is_zh else 'EN'})...")
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    blocks = parse_markdown_blocks(md_text)
    base_dir = os.path.dirname(os.path.abspath(md_path))

    doc = docx.Document()
    
    # Configure 0.85 inch / 0.90 inch margins
    for sec in doc.sections:
        sec.top_margin = Inches(0.85)
        sec.bottom_margin = Inches(0.85)
        sec.left_margin = Inches(0.9)
        sec.right_margin = Inches(0.9)

    font_family = 'Microsoft YaHei' if is_zh else 'Times New Roman'

    def append_styled_fragments(paragraph, fragments, base_size=Pt(9.5), default_color=RGBColor(0x22, 0x22, 0x22)):
        for frag in fragments:
            if frag['type'] == 'text':
                r = paragraph.add_run(frag['content'])
                r.font.name = font_family
                r.font.size = base_size
                r.font.bold = frag['bold']
                r.font.italic = frag['italic']
                r.font.color.rgb = default_color
            elif frag['type'] == 'code':
                r = paragraph.add_run(frag['content'])
                r.font.name = 'Consolas'
                r.font.size = Pt(base_size.pt * 0.9)
                r.font.color.rgb = RGBColor(0x88, 0x11, 0x11)
            elif frag['type'] == 'math':
                omml = latex_to_omml_element(frag['content'], is_display=False)
                if omml is not None:
                    paragraph._p.append(omml)
                else:
                    r = paragraph.add_run(frag['content'])
                    r.font.name = 'Cambria Math'
                    r.font.size = base_size
                    r.font.italic = True
                    r.font.color.rgb = RGBColor(0x11, 0x11, 0x11)
            elif frag['type'] == 'display_math':
                omml_para = latex_to_omml_element(frag['content'], is_display=True)
                if omml_para is not None:
                    paragraph._p.append(omml_para)
                else:
                    r = paragraph.add_run(frag['content'])
                    r.font.name = 'Cambria Math'
                    r.font.size = base_size
                    r.font.italic = True
                    r.font.color.rgb = RGBColor(0x11, 0x11, 0x11)

    for b_idx, block in enumerate(blocks):
        btype = block['type']

        if btype == 'heading':
            level = block['level']
            title = block['title']
            p = doc.add_paragraph()

            if level == 1:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(8)
                fragments = parse_inline(title)
                append_styled_fragments(p, fragments, base_size=Pt(16.5), default_color=RGBColor(0x11, 0x11, 0x11))
                for run in p.runs:
                    run.font.bold = True
            elif level == 2:
                p.paragraph_format.space_before = Pt(14)
                p.paragraph_format.space_after = Pt(4)
                fragments = parse_inline(title)
                append_styled_fragments(p, fragments, base_size=Pt(12), default_color=RGBColor(0x0d, 0x47, 0xa1))
                for run in p.runs:
                    run.font.bold = True
            elif level == 3:
                p.paragraph_format.space_before = Pt(9)
                p.paragraph_format.space_after = Pt(3)
                fragments = parse_inline(title)
                append_styled_fragments(p, fragments, base_size=Pt(10.5), default_color=RGBColor(0x22, 0x22, 0x22))
                for run in p.runs:
                    run.font.bold = True
            elif level >= 4:
                p.paragraph_format.space_before = Pt(6)
                p.paragraph_format.space_after = Pt(2)
                fragments = parse_inline(title)
                append_styled_fragments(p, fragments, base_size=Pt(9.5), default_color=RGBColor(0x33, 0x33, 0x33))
                for run in p.runs:
                    run.font.bold = True

        elif btype == 'paragraph':
            text = block['text']

            # Filter out foreign subtitle lines in Chinese paper
            if is_zh:
                s_strip = text.strip()
                if (s_strip.startswith('*Fig.') or 
                    s_strip.startswith('*Table') or 
                    s_strip.startswith('*Listing')):
                    continue

            p = doc.add_paragraph()
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_after = Pt(5)

            # Metadata formatting
            if text.startswith('**杨涵钦**') or text.startswith('**Hanqin Yang**') or '(Email: 2923165556@qq.com)' in text:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_after = Pt(2)
                fragments = parse_inline(text)
                append_styled_fragments(p, fragments, base_size=Pt(10), default_color=RGBColor(0x33, 0x33, 0x33))
            elif text.startswith('**中图法分类号**') or text.startswith('**CLC Number**'):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_after = Pt(10)
                fragments = parse_inline(text)
                append_styled_fragments(p, fragments, base_size=Pt(8.5), default_color=RGBColor(0x44, 0x44, 0x44))
            elif text.startswith('**关键词**') or text.startswith('**Keywords**'):
                p.paragraph_format.left_indent = Inches(0.35)
                p.paragraph_format.right_indent = Inches(0.35)
                p.paragraph_format.space_after = Pt(12)
                fragments = parse_inline(text)
                append_styled_fragments(p, fragments, base_size=Pt(9), default_color=RGBColor(0x22, 0x22, 0x22))
            elif text.startswith('**图 ') or text.startswith('**Fig. ') or text.startswith('**代码清单 ') or text.startswith('**Listing '):
                # Centered bold caption
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(8)
                fragments = parse_inline(text)
                append_styled_fragments(p, fragments, base_size=Pt(8.5), default_color=RGBColor(0x33, 0x33, 0x33))
                for run in p.runs:
                    run.font.bold = True
            elif text.startswith('**表 ') or text.startswith('**TABLE '):
                # Table caption
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(8)
                p.paragraph_format.space_after = Pt(3)
                fragments = parse_inline(text)
                append_styled_fragments(p, fragments, base_size=Pt(9.0), default_color=RGBColor(0x22, 0x22, 0x22))
                for run in p.runs:
                    run.font.bold = True
            else:
                fragments = parse_inline(text)
                append_styled_fragments(p, fragments, base_size=Pt(9.5), default_color=RGBColor(0x22, 0x22, 0x22))

        elif btype == 'list_item':
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_after = Pt(3)

            bullet = block['bullet']
            b_run = p.add_run(bullet + " ")
            b_run.font.name = font_family
            b_run.font.size = Pt(9.5)
            b_run.font.bold = True
            b_run.font.color.rgb = RGBColor(0x0d, 0x47, 0xa1)

            fragments = parse_inline(block['text'])
            append_styled_fragments(p, fragments, base_size=Pt(9.5), default_color=RGBColor(0x22, 0x22, 0x22))

        elif btype == 'display_math':
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            
            omml_para = latex_to_omml_element(block['content'], is_display=True)
            if omml_para is not None:
                p._p.append(omml_para)
            else:
                r = p.add_run(block['content'])
                r.font.name = 'Cambria Math'
                r.font.size = Pt(10)
                r.font.italic = True
                r.font.color.rgb = RGBColor(0x11, 0x11, 0x11)

        elif btype == 'blockquote':
            # Multi-block Academic Callout Box (Theorems, Propositions, Corollaries)
            tbl = doc.add_table(rows=1, cols=1)
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            tbl.autofit = False
            cell = tbl.rows[0].cells[0]
            cell.width = Inches(6.5)

            # Shading and left border (0d47a1 blue 2.25pt)
            shd = parse_xml(r'<w:shd {} w:fill="F8F9FA"/>'.format(nsdecls('w')))
            cell._tc.get_or_add_tcPr().append(shd)

            tblBorders = parse_xml(
                r'<w:tblBorders {} >'
                r'  <w:top w:val="none"/>'
                r'  <w:bottom w:val="none"/>'
                r'  <w:left w:val="single" w:sz="18" w:space="0" w:color="0d47a1"/>'
                r'  <w:right w:val="none"/>'
                r'  <w:insideH w:val="none"/>'
                r'  <w:insideV w:val="none"/>'
                r'</w:tblBorders>'.format(nsdecls('w'))
            )
            tbl._tbl.tblPr.append(tblBorders)

            subblocks = parse_blockquote_subblocks(block['content'])
            for s_idx, sblock in enumerate(subblocks):
                p_sub = cell.paragraphs[0] if s_idx == 0 else cell.add_paragraph()
                p_sub.paragraph_format.left_indent = Inches(0.12)
                p_sub.paragraph_format.right_indent = Inches(0.12)
                
                if sblock['type'] == 'display_math':
                    p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p_sub.paragraph_format.space_before = Pt(4)
                    p_sub.paragraph_format.space_after = Pt(4)
                    omml_para = latex_to_omml_element(sblock['content'], is_display=True)
                    if omml_para is not None:
                        p_sub._p.append(omml_para)
                    else:
                        r = p_sub.add_run(sblock['content'])
                        r.font.name = 'Cambria Math'
                        r.font.size = Pt(9.5)
                        r.font.italic = True
                elif sblock['type'] == 'list_item':
                    p_sub.paragraph_format.left_indent = Inches(0.25)
                    p_sub.paragraph_format.line_spacing = 1.15
                    p_sub.paragraph_format.space_after = Pt(2)
                    b_run = p_sub.add_run(sblock['bullet'] + " ")
                    b_run.font.name = font_family
                    b_run.font.size = Pt(9.0)
                    b_run.font.bold = True
                    b_run.font.color.rgb = RGBColor(0x0d, 0x47, 0xa1)
                    append_styled_fragments(p_sub, parse_inline(sblock['text']), base_size=Pt(9.0), default_color=RGBColor(0x22, 0x22, 0x22))
                else:
                    p_sub.paragraph_format.line_spacing = 1.15
                    p_sub.paragraph_format.space_after = Pt(3)
                    append_styled_fragments(p_sub, parse_inline(sblock['text']), base_size=Pt(9.0), default_color=RGBColor(0x22, 0x22, 0x22))

            p_after = doc.add_paragraph()
            p_after.paragraph_format.space_before = Pt(2)
            p_after.paragraph_format.space_after = Pt(3)

        elif btype == 'table':
            lines = block['lines']
            if len(lines) < 2:
                continue
                
            raw_header = [c.strip() for c in lines[0].split('|')[1:-1]]
            col_count = len(raw_header)
            
            raw_rows = []
            for row_line in lines[2:]:
                cells = [c.strip() for c in row_line.split('|')[1:-1]]
                if len(cells) == col_count:
                    raw_rows.append(cells)
                    
            row_count = len(raw_rows) + 1
            tbl = doc.add_table(rows=row_count, cols=col_count)
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            tbl.autofit = False

            total_w = 6.6
            w_per_col = total_w / col_count
            col_widths = [w_per_col] * col_count
            if col_count == 4:
                col_widths = [1.6, 1.7, 1.7, 1.6]
            elif col_count == 5:
                col_widths = [1.4, 1.3, 1.3, 1.3, 1.3]
            elif col_count == 7:
                col_widths = [1.3, 0.8, 1.0, 1.0, 0.8, 0.9, 0.8]
            elif col_count == 8:
                col_widths = [1.2, 0.6, 0.8, 0.9, 0.7, 0.8, 0.7, 0.9]

            # Header Row
            hdr_cells = tbl.rows[0].cells
            for c_idx, title in enumerate(raw_header):
                hdr_cells[c_idx].width = Inches(col_widths[c_idx])
                hdr_cells[c_idx].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                p = hdr_cells[c_idx].paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.line_spacing = 1.05
                shading = parse_xml(r'<w:shd {} w:fill="F4F6F7"/>'.format(nsdecls('w')))
                hdr_cells[c_idx]._tc.get_or_add_tcPr().append(shading)
                fragments = parse_inline(title)
                append_styled_fragments(p, fragments, base_size=Pt(8.5), default_color=RGBColor(0x11, 0x11, 0x11))
                for run in p.runs:
                    run.font.bold = True

            # Three-line table borders
            tblBorders = parse_xml(
                r'<w:tblBorders {} >'
                r'  <w:top w:val="single" w:sz="12" w:space="0" w:color="222222"/>'
                r'  <w:bottom w:val="single" w:sz="12" w:space="0" w:color="222222"/>'
                r'  <w:left w:val="none"/>'
                r'  <w:right w:val="none"/>'
                r'  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="E0E0E0"/>'
                r'  <w:insideV w:val="none"/>'
                r'</w:tblBorders>'.format(nsdecls('w'))
            )
            tbl._tbl.tblPr.append(tblBorders)

            # Data Rows
            for r_idx, row_values in enumerate(raw_rows):
                row_cells = tbl.rows[r_idx + 1].cells
                is_dsda = any("DSDA" in str(val) for val in row_values)
                for c_idx, val in enumerate(row_values):
                    row_cells[c_idx].width = Inches(col_widths[c_idx])
                    row_cells[c_idx].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                    p = row_cells[c_idx].paragraphs[0]
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER if c_idx > 0 else WD_ALIGN_PARAGRAPH.LEFT
                    p.paragraph_format.space_before = Pt(3)
                    p.paragraph_format.space_after = Pt(3)
                    p.paragraph_format.line_spacing = 1.05
                    
                    if is_dsda:
                        shading = parse_xml(r'<w:shd {} w:fill="EBF5FB"/>'.format(nsdecls('w')))
                        row_cells[c_idx]._tc.get_or_add_tcPr().append(shading)

                    # Handle <br> inside cells
                    sublines = val.split('<br>')
                    for s_idx, sline in enumerate(sublines):
                        if s_idx > 0:
                            p = row_cells[c_idx].add_paragraph()
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if c_idx > 0 else WD_ALIGN_PARAGRAPH.LEFT
                            p.paragraph_format.space_before = Pt(1)
                            p.paragraph_format.space_after = Pt(1)
                            p.paragraph_format.line_spacing = 1.05
                        fragments = parse_inline(sline.strip())
                        def_color = RGBColor(0x0d, 0x47, 0xa1) if is_dsda else RGBColor(0x33, 0x33, 0x33)
                        append_styled_fragments(p, fragments, base_size=Pt(8.2), default_color=def_color)
                        if is_dsda:
                            for run in p.runs:
                                run.font.bold = True

            p_tbl_after = doc.add_paragraph()
            p_tbl_after.paragraph_format.space_before = Pt(2)
            p_tbl_after.paragraph_format.space_after = Pt(4)

        elif btype == 'image':
            img_rel = block['src']
            img_full = os.path.join(base_dir, img_rel.replace('/', os.sep))
            if os.path.exists(img_full):
                p_img = doc.add_paragraph()
                p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_img.paragraph_format.space_before = Pt(6)
                p_img.paragraph_format.space_after = Pt(2)
                run = p_img.add_run()
                run.add_picture(img_full, width=Inches(6.0))
                # Note: We intentionally do NOT output block['alt'] as caption here,
                # because the markdown file immediately provides the bold caption paragraph!

        elif btype == 'code':
            tbl = doc.add_table(rows=1, cols=1)
            tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
            tbl.autofit = False
            cell = tbl.rows[0].cells[0]
            cell.width = Inches(6.5)

            shd = parse_xml(r'<w:shd {} w:fill="F4F6F7"/>'.format(nsdecls('w')))
            cell._tc.get_or_add_tcPr().append(shd)

            tblBorders = parse_xml(
                r'<w:tblBorders {} >'
                r'  <w:top w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>'
                r'  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>'
                r'  <w:left w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>'
                r'  <w:right w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>'
                r'  <w:insideH w:val="none"/>'
                r'  <w:insideV w:val="none"/>'
                r'</w:tblBorders>'.format(nsdecls('w'))
            )
            tbl._tbl.tblPr.append(tblBorders)

            p = cell.paragraphs[0]
            p.paragraph_format.left_indent = Inches(0.1)
            p.paragraph_format.right_indent = Inches(0.1)
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.line_spacing = 1.05

            r = p.add_run(block['content'])
            r.font.name = 'Consolas'
            r.font.size = Pt(8.0)
            r.font.color.rgb = RGBColor(0x22, 0x22, 0x22)

            p_after = doc.add_paragraph()
            p_after.paragraph_format.space_before = Pt(2)
            p_after.paragraph_format.space_after = Pt(4)

        elif btype == 'hr':
            pass

    doc.save(docx_path)
    file_size = os.path.getsize(docx_path)
    print(f"[+] Successfully compiled {docx_path} ({file_size} bytes)")

def compile_all():
    zh_md = 'docs/paper/beyond_surface_adaptation_zh.md'
    zh_docx = 'docs/paper/beyond_surface_adaptation_zh.docx'
    en_md = 'docs/paper/beyond_surface_adaptation.md'
    en_docx = 'docs/paper/beyond_surface_adaptation.docx'

    compile_md_to_docx(zh_md, zh_docx, is_zh=True)
    compile_md_to_docx(en_md, en_docx, is_zh=False)

if __name__ == '__main__':
    compile_all()
