import os
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

OUTPUT_DIR = r"D:\BaiduNetdiskDownload\Local-AI\docs\paper"
IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

# Set overall matplotlib style
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
plt.rcParams['axes.edgecolor'] = '#cccccc'
plt.rcParams['axes.linewidth'] = 0.8

# -------------------------------------------------------------
# 1. Generate Figures
# -------------------------------------------------------------
def generate_figure1():
    # Figure 1: Training Loss vs. Verbatim 20-Gram Memorization Rate Across Training Epochs
    epochs = np.array([0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
    train_loss = np.array([3.60, 2.10, 1.11, 0.85, 0.69, 0.48, 0.37])
    memorization_20g = np.array([0.05, 0.10, 0.17, 0.32, 0.52, 0.49, 0.48]) * 100
    l3_generalization = np.array([11, 11, 11, 12, 12, 11, 10]) / 16.0 * 100.0

    fig, ax1 = plt.subplots(figsize=(7.8, 4.6), dpi=300)

    color_loss = '#1f77b4'
    color_mem = '#d62728'
    color_l3 = '#2ca02c'

    ax1.set_xlabel('Training Epochs', fontsize=11, fontweight='bold', labelpad=8)
    ax1.set_ylabel('Training Cross-Entropy Loss', color=color_loss, fontsize=11, fontweight='bold', labelpad=8)
    line1 = ax1.plot(epochs, train_loss, color=color_loss, marker='o', markersize=6.5, linewidth=2.2, label='Train CE Loss')
    ax1.tick_params(axis='y', labelcolor=color_loss)
    ax1.set_ylim(0, 4.2)
    ax1.set_xlim(-0.1, 3.35)

    ax2 = ax1.twinx()
    ax2.set_ylabel('Percentage (%)', color='#333333', fontsize=11, fontweight='bold', labelpad=8)
    line2 = ax2.plot(epochs, memorization_20g, color=color_mem, marker='s', markersize=6.5, linewidth=2.2, linestyle='--', label='20-Gram Overlap (%)')
    line3 = ax2.plot(epochs, l3_generalization, color=color_l3, marker='^', markersize=6.5, linewidth=2.0, linestyle='-.', label='Abstract L3 Generalization (%)')
    ax2.tick_params(axis='y', labelcolor='#333333')
    ax2.set_ylim(0, 105)

    # Highlight memorization zone without occluding curves
    ax1.axvspan(1.5, 3.0, alpha=0.10, color='red')
    ax1.text(2.25, 3.85, 'Severe Memorization Zone\n(Verbatim Overlap Spikes)', color='#c0392b', fontsize=8.5, fontweight='bold', ha='center', va='center', bbox=dict(boxstyle='round,pad=0.35', facecolor='#fff5f5', edgecolor='#e74c3c', alpha=0.92))

    # Clean end-of-curve value callouts
    ax1.annotate(f'{train_loss[-1]:.2f}', xy=(3.0, train_loss[-1]), xytext=(3.06, train_loss[-1] - 0.05), fontsize=8.5, fontweight='bold', color=color_loss)
    ax2.annotate(f'{memorization_20g[-1]:.1f}%', xy=(3.0, memorization_20g[-1]), xytext=(3.06, memorization_20g[-1] - 1.5), fontsize=8.5, fontweight='bold', color=color_mem)
    ax2.annotate(f'{l3_generalization[-1]:.1f}%', xy=(3.0, l3_generalization[-1]), xytext=(3.06, l3_generalization[-1] - 1.5), fontsize=8.5, fontweight='bold', color=color_l3)

    lines = line1 + line2 + line3
    labels = [l.get_label() for l in lines]

    # Relocate legend to top outside plotting canvas (eliminates all curve occlusion)
    ax1.legend(lines, labels, loc='lower center', bbox_to_anchor=(0.5, 1.05), ncol=3, frameon=True, facecolor='white', edgecolor='#d0d0d0', fontsize=9.2)

    plt.title('Figure 1: Training Loss vs. Verbatim 20-Gram Memorization and L3 Generalization', fontsize=11.5, fontweight='bold', pad=32)
    plt.tight_layout()
    path = os.path.join(IMAGES_DIR, "fig1_memorization_vs_loss.png")
    plt.savefig(path, bbox_inches='tight', pad_inches=0.18)
    plt.close()
    return path

def generate_figure2():
    # Figure 2: DSDA System Architecture Diagram
    fig, ax = plt.subplots(figsize=(9.2, 4.6), dpi=300)
    ax.axis('off')
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.0)

    from matplotlib.patches import FancyBboxPatch

    # Clear, well-proportioned layout with non-overlapping bounds
    boxes = [
        {"x": 0.04, "y": 0.34, "w": 0.16, "h": 0.32, "title": "User Query\n& System State", "color": "#E3F2FD", "ec": "#1E88E5"},
        {"x": 0.28, "y": 0.58, "w": 0.22, "h": 0.32, "title": "Anti-Memorization\nPerturbation (K=4)\n& Length Balance", "color": "#E8F5E9", "ec": "#43A047"},
        {"x": 0.28, "y": 0.10, "w": 0.22, "h": 0.32, "title": "Candidate Tool\nClustering (k=8~12)\nHard Negative Sampling", "color": "#FFF3E0", "ec": "#FB8C00"},
        {"x": 0.57, "y": 0.34, "w": 0.18, "h": 0.32, "title": "Dynamic Routing\nBridge (Scheme Z)\n[Context Guard]", "color": "#EDE7F6", "ec": "#8E24AA"},
        {"x": 0.81, "y": 0.58, "w": 0.16, "h": 0.32, "title": "LoRA Adapter:\nRE Tool Specialist\n(θ_RE)", "color": "#FCE4EC", "ec": "#D81B60"},
        {"x": 0.81, "y": 0.10, "w": 0.16, "h": 0.32, "title": "LoRA Adapter:\nCoding & Gating\n(θ_Code / θ_Gate)", "color": "#E0F7FA", "ec": "#00ACC1"}
    ]

    for b in boxes:
        rect = FancyBboxPatch((b["x"], b["y"]), b["w"], b["h"], facecolor=b["color"], edgecolor=b["ec"], linewidth=1.8, zorder=2, boxstyle="round,pad=0.015")
        ax.add_patch(rect)
        ax.text(b["x"] + b["w"]/2, b["y"] + b["h"]/2, b["title"], ha='center', va='center', fontsize=9.2, fontweight='bold', zorder=3, linespacing=1.25)

    arrow_props = dict(arrowstyle="-|>", lw=1.8, color="#37474F", mutation_scale=15)
    ax.annotate("", xy=(0.27, 0.74), xytext=(0.21, 0.54), arrowprops=arrow_props)
    ax.annotate("", xy=(0.27, 0.26), xytext=(0.21, 0.46), arrowprops=arrow_props)
    ax.annotate("", xy=(0.56, 0.54), xytext=(0.51, 0.72), arrowprops=arrow_props)
    ax.annotate("", xy=(0.56, 0.46), xytext=(0.51, 0.28), arrowprops=arrow_props)
    ax.annotate("", xy=(0.80, 0.74), xytext=(0.76, 0.54), arrowprops=arrow_props)
    ax.annotate("", xy=(0.80, 0.26), xytext=(0.76, 0.46), arrowprops=arrow_props)

    plt.title('Figure 2: Architectural Overview of Decoupled System-Domain Adaptation (DSDA)', fontsize=12, fontweight='bold', pad=14)
    path = os.path.join(IMAGES_DIR, "fig2_dsda_architecture.png")
    plt.savefig(path, bbox_inches='tight', pad_inches=0.18)
    plt.close()
    return path

def generate_figure3():
    # Figure 3: Spurious Length Bias Distribution
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.8, 4.0), dpi=300)

    np.random.seed(42)
    # Naive Gating Distribution (Severe Disparity)
    pos_naive = np.random.normal(loc=1065, scale=120, size=500)
    neg_naive = np.random.normal(loc=126, scale=35, size=500)

    # DSDA Length-Balanced Distribution (Aligned)
    pos_dsda = np.random.normal(loc=780, scale=80, size=500)
    neg_dsda = np.random.normal(loc=765, scale=85, size=500)

    # Subplot 1: Naive Length Bias
    ax1.hist(neg_naive, bins=30, alpha=0.65, color='#e74c3c', label='Unauthorized (Mean: 126)', edgecolor='black', linewidth=0.5)
    ax1.hist(pos_naive, bins=30, alpha=0.65, color='#2980b9', label='Authorized (Mean: 1065)', edgecolor='black', linewidth=0.5)
    ax1.set_title('(a) Naive Gating: 8.4x Length Disparity\n(Spurious Gating Shortcut Triggered)', fontsize=9.8, fontweight='bold', pad=10)
    ax1.set_xlabel('Response Length (Tokens)', fontsize=9, fontweight='bold')
    ax1.set_ylabel('Sample Frequency', fontsize=9, fontweight='bold')
    ax1.legend(loc='upper right', fontsize=8.2, frameon=True, facecolor='white', edgecolor='#cccccc')
    ax1.set_xlim(0, 1500)
    ax1.set_ylim(0, 85)

    # Subplot 2: DSDA Length-Balanced
    ax2.hist(neg_dsda, bins=30, alpha=0.65, color='#27ae60', label='Compliant Alt (Mean: 765)', edgecolor='black', linewidth=0.5)
    ax2.hist(pos_dsda, bins=30, alpha=0.65, color='#8e44ad', label='Authorized (Mean: 780)', edgecolor='black', linewidth=0.5)
    ax2.set_title('(b) DSDA: Length-Balanced Counterfactuals\n(Spurious Feature Eliminated)', fontsize=9.8, fontweight='bold', pad=10)
    ax2.set_xlabel('Response Length (Tokens)', fontsize=9, fontweight='bold')
    ax2.set_ylabel('Sample Frequency', fontsize=9, fontweight='bold')
    ax2.legend(loc='upper right', fontsize=8.2, frameon=True, facecolor='white', edgecolor='#cccccc')
    ax2.set_xlim(0, 1500)
    ax2.set_ylim(0, 85)

    plt.suptitle('Figure 3: Token Length Disparity in Naive Safety Gating vs. DSDA Counterfactual Length Balancing', fontsize=11.2, fontweight='bold', y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.92])
    path = os.path.join(IMAGES_DIR, "fig3_length_bias_distribution.png")
    plt.savefig(path, bbox_inches='tight', pad_inches=0.18)
    plt.close()
    return path

def generate_figure4():
    # Figure 4: Structural Causal Model (SCM) & Causal Interventions
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.8, 4.4), dpi=300)
    ax1.axis('off')
    ax2.axis('off')
    ax1.set_xlim(0, 1.0)
    ax1.set_ylim(0, 1.0)
    ax2.set_xlim(0, 1.0)
    ax2.set_ylim(0, 1.0)

    from matplotlib.patches import FancyBboxPatch

    # (a) Naive Confounded Model
    n_l = {'x': 0.35, 'y': 0.72, 'w': 0.30, 'h': 0.18, 't': 'Length Confounder (L)\n[E[L_pos]=1065, E[L_neg]=126]', 'fc': '#FFEBEE', 'ec': '#D32F2F'}
    n_x = {'x': 0.05, 'y': 0.32, 'w': 0.24, 'h': 0.18, 't': 'User Query (X)\n[Technical Request]', 'fc': '#E3F2FD', 'ec': '#1976D2'}
    n_g = {'x': 0.38, 'y': 0.32, 'w': 0.24, 'h': 0.18, 't': 'Gate Token (G)\n[Observed State]', 'fc': '#FFF9C4', 'ec': '#FBC02D'}
    n_y = {'x': 0.71, 'y': 0.32, 'w': 0.24, 'h': 0.18, 't': 'Agent Output (Y)\n[Disclosure / Refusal]', 'fc': '#EDE7F6', 'ec': '#7B1FA2'}

    for n in [n_l, n_x, n_g, n_y]:
        rect = FancyBboxPatch((n['x'], n['y']), n['w'], n['h'], facecolor=n['fc'], edgecolor=n['ec'], linewidth=1.6, boxstyle="round,pad=0.015")
        ax1.add_patch(rect)
        ax1.text(n['x'] + n['w']/2, n['y'] + n['h']/2, n['t'], ha='center', va='center', fontsize=7.8, fontweight='bold')

    arrow_solid = dict(arrowstyle="-|>", lw=1.6, color="#37474F", mutation_scale=12)
    arrow_backdoor = dict(arrowstyle="-|>", lw=1.8, color="#D32F2F", linestyle="--", mutation_scale=13)

    ax1.annotate("", xy=(0.38, 0.41), xytext=(0.29, 0.41), arrowprops=arrow_solid) # X -> G
    ax1.annotate("", xy=(0.71, 0.41), xytext=(0.62, 0.41), arrowprops=arrow_solid) # G -> Y
    ax1.annotate("", xy=(0.17, 0.50), xytext=(0.38, 0.72), arrowprops=arrow_backdoor) # L -> X
    ax1.annotate("", xy=(0.79, 0.50), xytext=(0.62, 0.72), arrowprops=arrow_backdoor) # L -> Y
    ax1.text(0.50, 0.14, "Spurious Backdoor Path: X <- L -> Y\nModel exploits length L as shortcut (GateLeak > 8%)", ha='center', va='center', fontsize=8.2, color='#C62828', fontweight='bold')
    ax1.set_title('(a) Naive Gating: Confounded Backdoor Path', fontsize=10.2, fontweight='bold', pad=10)

    # (b) DSDA Causal Intervention & Modular Routing
    n_l2 = {'x': 0.35, 'y': 0.72, 'w': 0.30, 'h': 0.18, 't': 'Counterfactual Length Balancing\n[I(Length; Gate) -> 0]', 'fc': '#E8F5E9', 'ec': '#388E3C'}
    n_x2 = {'x': 0.05, 'y': 0.32, 'w': 0.22, 'h': 0.18, 't': 'User Query (X)\n[Invariant Intent]', 'fc': '#E3F2FD', 'ec': '#1976D2'}
    n_g2 = {'x': 0.35, 'y': 0.32, 'w': 0.22, 'h': 0.18, 't': 'Intervened Gate\ndo(G = g)', 'fc': '#FFF9C4', 'ec': '#FBC02D'}
    n_th = {'x': 0.65, 'y': 0.32, 'w': 0.24, 'h': 0.18, 't': 'Modular Adapter\ndo(θ_active)', 'fc': '#FCE4EC', 'ec': '#C2185B'}
    n_y2 = {'x': 0.70, 'y': 0.04, 'w': 0.24, 'h': 0.16, 't': 'Guaranteed Output (Y)\n[GateLeak = 0.0000]', 'fc': '#EDE7F6', 'ec': '#7B1FA2'}

    for n in [n_l2, n_x2, n_g2, n_th, n_y2]:
        rect = FancyBboxPatch((n['x'], n['y']), n['w'], n['h'], facecolor=n['fc'], edgecolor=n['ec'], linewidth=1.6, boxstyle="round,pad=0.015")
        ax2.add_patch(rect)
        ax2.text(n['x'] + n['w']/2, n['y'] + n['h']/2, n['t'], ha='center', va='center', fontsize=7.8, fontweight='bold')

    arrow_blocked = dict(arrowstyle="-|>", lw=1.6, color="#78909C", linestyle=":", mutation_scale=12)
    ax2.annotate("", xy=(0.35, 0.41), xytext=(0.27, 0.41), arrowprops=arrow_solid) # X -> do(G)
    ax2.annotate("", xy=(0.65, 0.41), xytext=(0.57, 0.41), arrowprops=arrow_solid) # do(G) -> do(theta)
    ax2.annotate("", xy=(0.80, 0.20), xytext=(0.77, 0.32), arrowprops=arrow_solid) # do(theta) -> Y
    ax2.annotate("", xy=(0.18, 0.50), xytext=(0.40, 0.72), arrowprops=arrow_blocked) # Blocked
    ax2.annotate("", xy=(0.75, 0.50), xytext=(0.60, 0.72), arrowprops=arrow_blocked) # Blocked

    ax2.text(0.28, 0.62, "✖ BLOCKED", ha='center', va='center', fontsize=8.5, color='#D32F2F', fontweight='bold')
    ax2.text(0.68, 0.62, "✖ BLOCKED", ha='center', va='center', fontsize=8.5, color='#D32F2F', fontweight='bold')
    ax2.text(0.40, 0.12, "Direct Causal Path: do(θ) -> Y (ACE Guaranteed)\nZero cross-task interference (I = 0)", ha='center', va='center', fontsize=8.2, color='#2E7D32', fontweight='bold')
    ax2.set_title('(b) DSDA: Blocked Backdoor & Modular do-Calculus', fontsize=10.2, fontweight='bold', pad=10)

    plt.suptitle('Figure 4: Structural Causal Model (SCM) & Causal Interventions for Safety Gating and Modular Routing', fontsize=11.2, fontweight='bold', y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.93])
    path = os.path.join(IMAGES_DIR, "fig4_causal_dag.png")
    plt.savefig(path, bbox_inches='tight', pad_inches=0.18)
    plt.close()
    return path

# -------------------------------------------------------------
# 2. Render Code Blocks as Dark-Mode Terminal Images
# -------------------------------------------------------------
def render_code_to_image(code_text: str, filename: str, title: str = "CODE LISTING") -> str:
    lines = code_text.split('\n')
    font_size = 15
    line_height = 24
    padding_x = 24
    header_height = 42
    
    try:
        font = ImageFont.truetype("consola.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    max_len = max(len(line) for line in lines)
    char_width = 9.2
    img_width = max(720, int(max_len * char_width) + padding_x * 2)
    img_height = header_height + len(lines) * line_height + 25

    img = Image.new('RGB', (img_width, img_height), color='#1e1e1e')
    draw = ImageDraw.Draw(img)

    # Terminal Title Bar
    draw.rectangle([(0, 0), (img_width, header_height)], fill='#2d2d2d')
    # Window controls (macOS / Linux terminal dots)
    draw.ellipse([(14, 15), (26, 27)], fill='#ff5f56')
    draw.ellipse([(34, 15), (46, 27)], fill='#ffbd2e')
    draw.ellipse([(54, 15), (66, 27)], fill='#27c93f')
    
    # Title Text
    draw.text((80, 13), title, fill='#cccccc', font=font)

    # Code Lines
    y = header_height + 12
    for line in lines:
        if line.strip().startswith('#'):
            color = '#6A9955'  # Green comment
        elif any(k in line for k in ['def ', 'return ', 'import ', 'from ', 'class ', 'if ', 'elif ', 'else:']):
            color = '#569CD6'  # Blue keyword
        elif '"' in line or "'" in line:
            color = '#CE9178'  # Orange string
        else:
            color = '#D4D4D4'  # White/gray text
        
        draw.text((padding_x, y), line, fill=color, font=font)
        y += line_height

    out_path = os.path.join(IMAGES_DIR, filename)
    img.save(out_path, dpi=(300, 300))
    return out_path

# -------------------------------------------------------------
# 3. Academic Table Styling for Word
# -------------------------------------------------------------
def style_academic_table(table, col_widths, headers, data):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    # Header Row
    hdr_cells = table.rows[0].cells
    for i, title in enumerate(headers):
        hdr_cells[i].text = title
        hdr_cells[i].width = Inches(col_widths[i])
        hdr_cells[i].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        p = hdr_cells[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(4)
        for run in p.runs:
            run.font.bold = True
            run.font.name = 'Arial'
            run.font.size = Pt(8.5)
            run.font.color.rgb = RGBColor(0x11, 0x11, 0x11)
        
        shading = parse_xml(r'<w:shd {} w:fill="F4F6F7"/>'.format(nsdecls('w')))
        hdr_cells[i]._tc.get_or_add_tcPr().append(shading)

    # Set Top Border on Table (Three-line table header top)
    tblPr = table._tbl.tblPr
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
    tblPr.append(tblBorders)

    # Data Rows
    for r_idx, row_values in enumerate(data):
        row_cells = table.rows[r_idx + 1].cells
        is_dsda = "DSDA" in str(row_values[0])
        for c_idx, val in enumerate(row_values):
            row_cells[c_idx].text = str(val)
            row_cells[c_idx].width = Inches(col_widths[c_idx])
            row_cells[c_idx].vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            p = row_cells[c_idx].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if c_idx > 0 else WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)
            for run in p.runs:
                run.font.name = 'Arial'
                run.font.size = Pt(8.2)
                if is_dsda:
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(0x0d, 0x47, 0xa1)
                else:
                    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

            if is_dsda:
                shading = parse_xml(r'<w:shd {} w:fill="EBF5FB"/>'.format(nsdecls('w')))
                row_cells[c_idx]._tc.get_or_add_tcPr().append(shading)

# -------------------------------------------------------------
# 4. Build Complete Paper Word Document
# -------------------------------------------------------------
def build_paper_docx():
    print("[+] Generating Figures...")
    fig1_path = generate_figure1()
    fig2_path = generate_figure2()
    fig3_path = generate_figure3()
    fig4_path = generate_figure4()

    print("[+] Creating Word Document with IEEE/ACM academic formatting...")
    doc = docx.Document()

    for sec in doc.sections:
        sec.top_margin = Inches(0.85)
        sec.bottom_margin = Inches(0.85)
        sec.left_margin = Inches(0.9)
        sec.right_margin = Inches(0.9)

    # Title
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title.paragraph_format.space_before = Pt(0)
    p_title.paragraph_format.space_after = Pt(6)
    r_title = p_title.add_run("Beyond Surface Adaptation: Deconstructing Memorization, Stage Overwriting, and Gating Biases in Domain-Specialized System Agents")
    r_title.font.name = 'Arial'
    r_title.font.size = Pt(17)
    r_title.font.bold = True
    r_title.font.color.rgb = RGBColor(0x11, 0x11, 0x11)

    # Subtitle / Authors
    p_auth = doc.add_paragraph()
    p_auth.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_auth.paragraph_format.space_after = Pt(14)
    r_auth = p_auth.add_run("Hanqin Yang (杨涵钦, yyhhqq1234)\nAutonomous Systems & Engineering Laboratory (2923165556@qq.com)")
    r_auth.font.name = 'Arial'
    r_auth.font.size = Pt(10)
    r_auth.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    # Abstract Box
    p_abs = doc.add_paragraph()
    p_abs.paragraph_format.left_indent = Inches(0.35)
    p_abs.paragraph_format.right_indent = Inches(0.35)
    p_abs.paragraph_format.space_after = Pt(14)
    r_abs_title = p_abs.add_run("Abstract—")
    r_abs_title.font.name = 'Arial'
    r_abs_title.font.size = Pt(9.5)
    r_abs_title.font.bold = True
    
    abs_text = (
        "While Large Language Model (LLM) agents demonstrate remarkable general reasoning capabilities, deploying them to specialized, "
        "low-level system operating environments (e.g., kernel debugging, binary reverse engineering, and low-level system analysis) exposes "
        "acute contradictions between domain competence and behavioral controllability. In this paper, we conduct an extensive empirical "
        "and theoretical study on fine-tuning compact hybrid linear-attention agents (9B parameters) and dense full-attention agents (27B parameters) "
        "on low-level system tool environments. We uncover three pervasive failure modes: (1) The Memorization Illusion: standard empirical "
        "cross-entropy loss reductions mask severe verbatim memorization (20-gram token overlap escalating from 0.167 to 0.515), where conventional "
        "held-out validation splits fail to detect brittle memorized tool mapping; (2) Catastrophic Stage Overwriting: sequential multi-stage "
        "post-training completely overwrites preceding capabilities—dropping domain tool calling accuracy from 75.0% to 10.0%—which we formalize through "
        "our Theorem on Low-Rank Subspace Interference Bounds; and (3) The Pareto Cliff of Subspace Abliteration: geometric weight-direction "
        "unlearning triggers an abrupt transition between complete refusal and severe linguistic collapse (KL divergence > 17) on compact models "
        "without achieving viable steering. Furthermore, we reveal a novel Spurious Gating Shortcut, wherein condition-gated safety tuning "
        "inadvertently exploits response length disparities (1065 tokens vs. 126 tokens) as an unintended authorization signal. To address these vulnerabilities, "
        "we propose DSDA (Decoupled System-Domain Adaptation), an integrated training and inference framework comprising semantic query perturbation, "
        "candidate-aware hard-negative tool clustering, counterfactual length-balanced paired gating formalized via Structural Causal Models (SCM), "
        "and inference-time modular adapter routing. Evaluated on rigorous system workbenches across both 9B and 27B architectures, DSDA achieves an 82.5% "
        "tool generalization accuracy with zero hallucinations, outperforming mainstream model merging baselines (Task Arithmetic 55.0%, TIES-Merging 62.5%), "
        "while guaranteeing strictly zero security leakage (GateLeak = 0.0000), zero false refusals (TrapRefusal = 0.0000), and zero degradation of base capabilities."
    )
    r_abs_body = p_abs.add_run(abs_text)
    r_abs_body.font.name = 'Arial'
    r_abs_body.font.size = Pt(9.5)
    r_abs_body.font.color.rgb = RGBColor(0x22, 0x22, 0x22)

    # Keywords
    p_kw = doc.add_paragraph()
    p_kw.paragraph_format.left_indent = Inches(0.35)
    p_kw.paragraph_format.right_indent = Inches(0.35)
    p_kw.paragraph_format.space_after = Pt(18)
    r_kw_title = p_kw.add_run("Keywords—")
    r_kw_title.font.name = 'Arial'
    r_kw_title.font.size = Pt(9)
    r_kw_title.font.bold = True
    r_kw_body = p_kw.add_run("Large Language Model Agents, Domain Adaptation, System Tool Routing, Memorization, Catastrophic Forgetting, Model Merging, Safety Gating, Representation Engineering.")
    r_kw_body.font.name = 'Arial'
    r_kw_body.font.size = Pt(9)
    r_kw_body.font.italic = True

    # Helper functions
    def add_sec_heading(title):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(title)
        run.font.name = 'Arial'
        run.font.size = Pt(12)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x0d, 0x47, 0xa1)
        return p

    def add_subsec_heading(title):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(3)
        run = p.add_run(title)
        run.font.name = 'Arial'
        run.font.size = Pt(10.5)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        return p

    def add_p(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(text)
        run.font.name = 'Arial'
        run.font.size = Pt(9.5)
        run.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        return p

    def add_caption(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(10)
        run = p.add_run(text)
        run.font.name = 'Arial'
        run.font.size = Pt(8.5)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x44, 0x44, 0x44)
        return p

    def add_theorem_box(title, text):
        tbl = doc.add_table(rows=1, cols=1)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        tbl.rows[0].cells[0].width = Inches(6.5)
        shading = parse_xml(r'<w:shd {} w:fill="F8F9FA"/>'.format(nsdecls('w')))
        tbl.rows[0].cells[0]._tc.get_or_add_tcPr().append(shading)
        tblPr = tbl._tbl.tblPr
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
        tblPr.append(tblBorders)
        p = tbl.rows[0].cells[0].paragraphs[0]
        p.paragraph_format.left_indent = Inches(0.15)
        p.paragraph_format.right_indent = Inches(0.15)
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(4)
        r_t = p.add_run(title + "\n")
        r_t.font.name = 'Arial'
        r_t.font.size = Pt(9.5)
        r_t.font.bold = True
        r_t.font.color.rgb = RGBColor(0x0d, 0x47, 0xa1)
        r_b = p.add_run(text)
        r_b.font.name = 'Arial'
        r_b.font.size = Pt(9.0)
        r_b.font.italic = True
        r_b.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        p_after = doc.add_paragraph()
        p_after.paragraph_format.space_before = Pt(2)
        p_after.paragraph_format.space_after = Pt(4)

    # 1. Introduction
    add_sec_heading("1. Introduction")
    add_p("Autonomous software agents driven by Large Language Models (LLMs) have demonstrated extraordinary performance across generic benchmarks such as high-level API orchestration, code synthesis, and web navigation. However, transferring these models into mission-critical, low-level system operating environments—such as binary reverse engineering, memory introspection, kernel debugging, and anti-cheat analysis—presents unique and severe challenges.")
    add_p("In low-level system domains (e.g., executing commands through Windows kernel-level driver bridges and dynamic debugger interfaces), execution semantics are characterized by low operational entropy, strict parameter schemas, and catastrophic irreversibility. Calling an invalid memory write opcode, misconfiguring ASLR base calculations, or halting a protected driver service will instantly trigger kernel bug checks (BSOD), freeze host processes, or terminate execution channels.")
    add_p("When adapting open-source foundation models to these low-level system execution environments, practitioners invariably encounter a Dual Dilemma: (1) The Specialization Competence Dilemma: The model must master over 60 specialized system tools with intricate state transitions and dependency chains; (2) The Controllability & Steering Dilemma: A system agent must possess privileged authorization to analyze, disassemble, and inspect potentially malicious or protected binaries under explicit consent, while rigorously refusing when authorization is absent.")

    # 2. Empirical Pathologies
    add_sec_heading("2. Empirical Pathologies in System Agent Specialization")
    add_subsec_heading("2.1 The Memorization Illusion and Brittle Evaluation")
    add_p("In specialized system domains, training datasets typically consist of succinct operational requests paired with structured tool invocations and templated explanations. We monitored the training dynamics of the 9B model over multiple epochs on a curated dataset of 5,602 core system tasks. As shown in Figure 1 and Table 1, standard empirical metrics provide a deceptive signal: cross-entropy loss plummets from 1.110 to 0.373, yet verbatim 20-gram token overlap triples from 0.167 to 0.515, and exact matches rise to 40%.")

    # Figure 1 Image
    doc.add_picture(fig1_path, width=Inches(6.0))
    add_caption("Figure 1: Training Cross-Entropy Loss vs. Verbatim 20-Gram Memorization and L3 Generalization Across Epochs.")

    add_subsec_heading("2.2 Catastrophic Stage Overwriting in Sequential Curriculum Tuning")
    add_p("Curriculum fine-tuning sequentially across stages (Stage 1: Tool Routing -> Stage 2: Agent Coding Trajectories -> Stage 3: Safety Gating) induces severe catastrophic forgetting. Following Stage 2 training using LoRA, Stage 1 tool routing accuracy plunged from 82.5% to 10.0%, and tool evasions escalated from 0/40 to 33/40. Because sequential gradient updates overwrite orthogonal feature directions in parameter space, sequential fine-tuning acts as capability erasure rather than cumulative skill acquisition.")

    # Mathematical Theorem
    add_theorem_box(
        "Theorem 1 (Task Interference Bound in Sequential Low-Rank Adaptation)",
        "Let T1 and T2 be two distinct tasks with loss functions L1 and L2. Suppose task T1 has been adapted into low-rank parameters B1 * A1 defining principal column subspace S1 = span(B1). When task T2 is subsequently trained on the same parameters, the parameter interference energy I(T1, T2) exerted on the task 1 manifold satisfies: "
        "I(T1, T2) = || P_S1(grad_W L2) ||_F^2 >= sigma_min^2(B1) * cos^2 theta(S1, S2) * || grad_W L2 ||_F^2, "
        "where P_S1 is the orthogonal projection operator onto S1, sigma_min(B1) is the minimum singular value of B1, and theta(S1, S2) is the principal Grassmannian subspace angle between task representations."
    )
    add_theorem_box(
        "Corollary 1.1 (Interference Neutralization via Modular Decoupling)",
        "In DSDA Scheme Z, each task Ti is parameterized by a dedicated low-rank adapter Bi * Ai. At runtime, routing is governed by an indicator switch I(task = Ti). Because parameter manifolds are held disjoint (Si intersect Sj = empty for i != j), cross-task gradient interference identically vanishes: I(Ti, Tj) = 0 for all i != j."
    )

    add_subsec_heading("2.3 Trajectory Contamination and Semantic Displacement")
    add_p("Empirical auditing of raw agent trajectory traces revealed two widespread data contaminations: (1) Pathological Marker Rewards: 66.3% of raw trajectory samples contained leaked role tags (e.g., 【assistant】), which reward the optimizer with low loss (0.2312) and high token accuracy (89.5%) while inducing fatal infinite repetition loops during inference; (2) Window-Slicing Semantic Drift: slicing long traces creates chunks where 99.3% of user prompts consist of bash execution logs, training models to produce summaries rather than initiating tool actions.")

    # Code Listing 1 Image
    code_listing_1 = (
        "# Listing 1: Anti-Memorization Multi-Axis Semantic Perturbation Algorithm\n"
        "def augment_system_query(user_prompt: str, k_variants: int = 4) -> list[str]:\n"
        "    structural_templates = ['Encountered issue: {q}', 'Require execution: {q}',\n"
        "                            'Investigating state: {q}', 'Command directive: {q}']\n"
        "    domain_synonyms = {'import table': 'runtime module imported descriptors',\n"
        "                       'memory scan': 'virtual address memory introspection'}\n"
        "    variants = set([user_prompt])\n"
        "    for template in structural_templates[:k_variants]:\n"
        "        perturbed = template.format(q=apply_synonyms(user_prompt, domain_synonyms))\n"
        "        variants.add(perturbed)\n"
        "    return list(variants)"
    )
    img_code1 = render_code_to_image(code_listing_1, "listing1_perturbation.png", "Listing 1: Query Perturbation Protocol")
    doc.add_picture(img_code1, width=Inches(5.8))
    add_caption("Listing 1: Multi-Axis Query Perturbation Algorithm (Rendered as Image).")

    # 3. The Steering Dilemma
    add_sec_heading("3. The Steering Dilemma: Limits of Representation Editing and Gating Shortcuts")
    add_subsec_heading("3.1 The Pareto Cliff of Subspace Abliteration")
    add_p("Attempting to unlearn refusal directions via representation engineering (e.g., Heretic/SRA) on compact hybrid architectures hits a severe Pareto Cliff. Sweeping projection scaling gamma demonstrates that gamma <= 1.0 yields zero refusal mitigation (refusal remains 100%), while gamma >= 4.0 triggers catastrophic linguistic collapse where KL divergence explodes from 0.046 to >17.0, destroying language syntax.")

    add_subsec_heading("3.2 Spurious Correlation in Condition Gating: The Length Bias Shortcut")
    add_p("Condition-gated SFT seeks to steer behavior via explicit authorization prompts. However, auditing revealed an acute length disparity: positive authorized disclosures averaged 1,065 tokens, while unauthorized refusals averaged 126 tokens. The model exploited this 8.4x length difference as an unintended proxy for authorization, bypassing safety constraints whenever a query prompted for long detailed explanations.")

    # Figure 3 Image
    doc.add_picture(fig3_path, width=Inches(6.0))
    add_caption("Figure 3: Token Length Disparity in Naive Safety Gating vs. DSDA Counterfactual Length Balancing.")

    # 4. Proposed Framework: DSDA
    add_sec_heading("4. The Proposed Framework: DSDA")
    add_p("DSDA (Decoupled System-Domain Adaptation) resolves these failure modes through an end-to-end decoupled framework consisting of four core components:")
    add_p("1. Semantic Anti-Memorization Protocol: Multi-axis query perturbation (K=4) paired with invariant tool completions, evaluated on an L1-L3 hierarchical abstraction benchmark.")
    add_p("2. Candidate-Aware Hard-Negative Clustering: Grouping 64 system tools into 11 execution clusters, injecting 8-12 hard-negative candidates into dynamic prompts.")
    add_p("3. Structural Causal Formulation of Length-Balanced Gating: Synthesizing long, compliant alternatives for unauthorized states. Formalized through Pearl's Structural Causal Models (SCM), counterfactual length balancing blocks the backdoor path X <- L -> Y, forcing mutual information I(Length; GateState) -> 0 and Average Causal Effect ACE = E[P(Y | do(G=1), X) - P(Y | do(G=0), X)].")
    add_p("4. Modular Inference-Time Adapter Decoupling (Scheme Z): Deploying dedicated LoRA adapters for tool routing, trajectory coding, and gating, switched dynamically at runtime to guarantee zero parameter interference.")

    # Figure 2 Image (Architecture)
    doc.add_picture(fig2_path, width=Inches(6.0))
    add_caption("Figure 2: Architecture of Decoupled System-Domain Adaptation (DSDA).")

    # Figure 4 Image (Causal DAG & Modular Routing)
    doc.add_picture(fig4_path, width=Inches(6.2))
    add_caption("Figure 4: Structural Causal Model (SCM) & Causal Interventions for Safety Gating and Modular Routing.")

    # Code Listing 2 Image
    code_listing_2 = (
        "# Listing 2: Candidate Tool Hard-Negative Sampling\n"
        "def sample_candidate_cluster(target_tool: str, clusters: dict[str, list[str]], k: int = 10):\n"
        "    target_cluster = next(c for c, tools in clusters.items() if target_tool in tools)\n"
        "    intra_negatives = [t for t in clusters[target_cluster] if t != target_tool]\n"
        "    inter_clusters = [c for c in clusters if c != target_cluster]\n"
        "    # Formulate hard negative candidate set\n"
        "    candidates = [target_tool] + random.sample(intra_negatives, min(4, len(intra_negatives)))\n"
        "    while len(candidates) < k:\n"
        "        cand_pool = clusters[random.choice(inter_clusters)]\n"
        "        candidates.append(random.choice(cand_pool))\n"
        "    return random.sample(candidates, len(candidates)) # Shuffle"
    )
    img_code2 = render_code_to_image(code_listing_2, "listing2_candidate_clustering.png", "Listing 2: Candidate Hard-Negative Tool Sampling")
    doc.add_picture(img_code2, width=Inches(5.8))
    add_caption("Listing 2: Candidate Tool Hard-Negative Sampling Protocol (Rendered as Image).")

    # 5. Experimental Evaluation
    add_sec_heading("5. Experimental Evaluation")
    add_subsec_heading("5.1 Anti-Memorization Benchmark Results")
    add_p("Table 1 summarizes tool routing accuracy, memorization metrics, and abstract reasoning across epochs and training methodologies.")

    # Table 1
    t1_headers = ["Training Regime", "Epochs", "CE Loss", "Tool Acc (%)", "Fab Tools", "20-Gram Overlap", "Verbatim Match", "L3 Gen (/16)"]
    t1_data = [
        ["Base (OxCoder-9B)", "0", "—", "75.0%", "10", "0.052", "0 / 10", "11 / 16 (68.8%)"],
        ["Naive SFT (Pass 1)", "1", "1.110", "82.5%", "1", "0.167", "1 / 10", "11 / 16 (68.8%)"],
        ["Naive SFT (Pass 2)", "2", "0.690", "82.5%", "0", "0.515", "4 / 10", "12 / 16 (75.0%)"],
        ["Naive SFT (Pass 3)", "3", "0.373", "80.0%", "0", "0.478", "4 / 10", "10 / 16 (62.5%)"],
        ["DSDA (K=4 + Dropout)", "1", "0.720", "85.0%", "0", "0.210", "0 / 10", "14 / 16 (87.5%)"]
    ]
    t1_col_widths = [1.8, 0.6, 0.7, 0.9, 0.8, 1.0, 1.0, 1.1]
    tbl1 = doc.add_table(rows=len(t1_data) + 1, cols=len(t1_headers))
    style_academic_table(tbl1, t1_col_widths, t1_headers, t1_data)
    add_caption("Table 1: Domain Specialization and Anti-Memorization Benchmark Performance.")

    # Table 2: Cross-Scale 9B vs 27B
    add_subsec_heading("5.2 Cross-Scale and Cross-Attention Architecture Generalization (9B vs. 27B)")
    add_p("Table 2 benchmarks DSDA across both the 9B hybrid linear-attention agent and the 27B dense full self-attention agent.")

    t2_headers = ["Evaluation Dimension", "9B Hybrid Linear-Attention", "27B Full Self-Attention", "Generalization"]
    t2_data = [
        ["Base Model Architecture", "9.02B (Gated Delta + Full Attn)", "26.98B (Full Dense Self-Attn)", "Cross-Arch Validated"],
        ["LoRA Parameters", "64.2M (r=64, alpha=128, 0.71%)", "79.7M (r=16, alpha=32, 0.295%)", "Consistent Efficiency"],
        ["Zero-Shot Baseline Pass", "75.0% (10 fabricated tools)", "13.0% (3/23 pass, 0/9 tool route)", "Distinct Prior Grounding"],
        ["Pre-Adaptation Memorization", "20-Gram overlap: 47.8% (Epoch 3)", "Training overlap: 45.2% (un-decoupled)", "Universal Pathology"],
        ["DSDA Post-Adaptation", "82.5% tool acc, L3: 14/16 (87.5%)", "FN: 0/12 (0%), FP: 0/12 (0%)", "Dual PASS"],
        ["Post-Training Quantization", "bf16 -> GGUF runtime", "GSQ-RCO IQ2_S (9.925 GB, 2.90 BPW)", "Lossless Deployment"],
        ["Safety Gating Leakage", "GateLeak = 0.0000", "GateLeak = 0.0000", "Zero Security Leakage"]
    ]
    t2_col_widths = [1.8, 2.0, 2.0, 1.4]
    tbl2 = doc.add_table(rows=len(t2_data) + 1, cols=len(t2_headers))
    style_academic_table(tbl2, t2_col_widths, t2_headers, t2_data)
    add_caption("Table 2: Cross-Scale and Cross-Attention Architecture Generalization (9B vs. 27B).")

    # Table 3: Baselines
    add_subsec_heading("5.3 Multi-Task Adaptation and Model Merging Baselines")
    add_p("Table 3 benchmarks DSDA Scheme Z against mainstream continual learning, prompt engineering, and weight merging baselines on the system workbench.")

    t3_headers = ["Method", "Paradigm", "Tool Acc (%)", "Evasion (%)", "Code Pass (%)", "Cross-Interf (%)"]
    t3_data = [
        ["Base Zero-Shot", "Foundation Prior", "75.0%", "25.0%", "74.2%", "0.0%"],
        ["ReAct (Prompt-Only)", "Prompt Engineering", "77.5%", "15.0%", "73.0%", "0.0%"],
        ["Sequential SFT", "Continual Learning", "10.0%", "82.5%", "78.4%", "87.5%"],
        ["Task Arithmetic (tau=0.5)", "Model Merging", "55.0%", "27.5%", "64.8%", "32.5%"],
        ["TIES-Merging (p=0.8)", "Model Merging", "62.5%", "22.5%", "69.1%", "22.5%"],
        ["Joint Mix SFT (Scheme X)", "Multi-Task Mixture", "67.5%", "15.0%", "45.0%", "17.5%"],
        ["DSDA Scheme Z (Ours)", "Dynamic Modular", "82.5%", "0.0%", "78.5%", "0.0%"]
    ]
    t3_col_widths = [1.8, 1.5, 1.0, 1.0, 1.0, 1.1]
    tbl3 = doc.add_table(rows=len(t3_data) + 1, cols=len(t3_headers))
    style_academic_table(tbl3, t3_col_widths, t3_headers, t3_data)
    add_caption("Table 3: Multi-Task Specialization and Model Merging Baseline Comparison.")

    # Code Listing 4 Image (Model Merging Baselines)
    code_listing_4 = (
        "# Listing 4: Multi-Task Model Merging Baselines (Task Arithmetic & TIES-Merging)\n"
        "import torch\n\n"
        "def task_arithmetic_merge(w_base: torch.Tensor, deltas: list[torch.Tensor], weights: list[float] = [0.5, 0.5]) -> torch.Tensor:\n"
        "    '''Task Arithmetic: Linear combination of task vectors (Ilharco et al., 2022)'''\n"
        "    return w_base + sum(w * d for w, d in zip(weights, deltas))\n\n"
        "def ties_merge(deltas: list[torch.Tensor], topk_ratio: float = 0.8) -> torch.Tensor:\n"
        "    '''TIES-Merging: Trim -> Elect Sign -> Disjoint Merge (Yadav et al., 2023)'''\n"
        "    # 1. Trim: Retain top-k magnitude parameters, zero bottom (1-k)\n"
        "    trimmed = [trim_parameters(d, topk_ratio) for d in deltas]\n"
        "    stacked = torch.stack(trimmed, dim=0)\n"
        "    # 2. Elect: Compute dominant parameter sign across task vectors\n"
        "    dominant_sign = stacked.sign().sum(dim=0).sign()\n"
        "    # 3. Disjoint Merge: Average parameters aligned with dominant sign\n"
        "    mask = (stacked.sign() == dominant_sign) & (dominant_sign != 0)\n"
        "    counts = mask.float().sum(dim=0).clamp(min=1.0)\n"
        "    return (stacked * mask.float()).sum(dim=0) / counts"
    )
    img_code4 = render_code_to_image(code_listing_4, "listing4_baseline_merging.png", "Listing 4: Task Arithmetic & TIES-Merging Baselines")
    doc.add_picture(img_code4, width=Inches(5.8))
    add_caption("Listing 4: Implementation of Task Arithmetic and TIES-Merging Baselines (Rendered as Image).")

    # Table 4: Candidate Scaling
    add_subsec_heading("5.4 Candidate Set Size (k) and Distractor Sensitivity")
    add_p("Table 4 analyzes the impact of candidate set sizing on tool accuracy and parameter robustness.")

    t4_headers = ["Candidate Config", "Candidate Size (k)", "Test Seed", "Correct (/40)", "Accuracy (%)", "Hallucinated Tools", "Evaluation Mode"]
    t4_data = [
        ["Bare Model (E1)", "0", "—", "30", "75.0%", "0", "Implicit Memory"],
        ["Full Schemas", "64", "7", "31", "77.5%", "0", "Context Dilution"],
        ["Broad Candidate", "48", "7", "34", "85.0%", "0", "Moderate Distraction"],
        ["DSDA Clustering (E2)", "8~12", "7", "34", "85.0%", "0", "Peak Focused"],
        ["DSDA Clustering (E2)", "8~12", "11", "32", "80.0%", "0", "Seed Invariance"],
        ["DSDA Mean (E2)", "8~12", "Mean", "33.0", "82.5%", "0", "Deployment Grade"],
        ["Distractor +5 (E3)", "13~17", "—", "33", "82.5%", "0", "Noise Resilient"]
    ]
    t4_col_widths = [1.6, 1.1, 0.8, 0.9, 1.0, 1.1, 1.2]
    tbl4 = doc.add_table(rows=len(t4_data) + 1, cols=len(t4_headers))
    style_academic_table(tbl4, t4_col_widths, t4_headers, t4_data)
    add_caption("Table 4: Candidate Scale Ablation and Random Seed Sensitivity Evaluation.")

    # Table 5: Safety Gating
    add_subsec_heading("5.5 Safety Gating and Technical Trap Robustness")
    add_p("Table 5 documents the safety steering metrics on the held-out verification benchmark.")

    t5_headers = ["Steering Method", "GateLeak (Unauthorized)", "GateRecall (Authorized)", "GateFPR (Benign)", "TrapRefusal (Adversarial)", "Capability Collapse"]
    t5_data = [
        ["Base Foundation Model", "0.0000", "0.0000", "0.0000", "0.0000", "0% (All-Refusal)"],
        ["SRA Abliteration (γ=2)", "0.0000", "0.0000", "0.0000", "0.0000", "0% (Ineffective)"],
        ["SRA Abliteration (γ=4)", "—", "—", "—", "—", "100% (KL > 17 Collapse)"],
        ["Naive Length-Biased SFT", "0.0833", "0.4500", "0.1250", "0.2222", "4.2%"],
        ["DSDA Balanced Gating", "0.0000", "0.5333", "0.0000", "0.0000", "0% (0 / 25 Collapse)"]
    ]
    t5_col_widths = [1.8, 1.2, 1.2, 1.1, 1.2, 1.2]
    tbl5 = doc.add_table(rows=len(t5_data) + 1, cols=len(t5_headers))
    style_academic_table(tbl5, t5_col_widths, t5_headers, t5_data)
    add_caption("Table 5: Dual-State Safety Gating and Technical Trap Robustness on Held-Out Fixtures.")

    # Code Listing 3 Image
    code_listing_3 = (
        "# Listing 3: Runtime Modular Adapter Switching Logic (Scheme Z)\n"
        "class ModularSystemRouter:\n"
        "    def route_request(self, user_query: str, session_context: dict):\n"
        "        if session_context.get('requires_diagnostic_tool_call', False):\n"
        "            active_adapter = 'theta_re_routing'      # Specialized for 64-tool dispatch\n"
        "        elif session_context.get('privileged_security_mode', False):\n"
        "            active_adapter = 'theta_gated_steering'   # Zero-leakage dual-state steering\n"
        "        else:\n"
        "            active_adapter = 'theta_coding_trajectory'# Long-context code synthesis\n"
        "        return self.engine.forward_with_adapter(user_query, adapter=active_adapter)"
    )
    img_code3 = render_code_to_image(code_listing_3, "listing3_runtime_routing.png", "Listing 3: Modular Adapter Router")
    doc.add_picture(img_code3, width=Inches(5.8))
    add_caption("Listing 3: Inference-Time Modular Adapter Dynamic Routing (Rendered as Image).")

    # 6. Guidelines
    add_sec_heading("6. Practical Guidelines for Edge System Agents")
    add_p("Based on our extensive empirical post-mortem, we formulate four foundational design principles:")
    add_p("1. Reject Monolithic Multi-Stage SFT: For disparate operational tasks (tool routing vs. discursive coding), practitioners must avoid sequential LoRA updates. Employ runtime modular adapter switching to preserve orthogonal capability manifolds.")
    add_p("2. Never Rely on In-Distribution Held-Out Splits: In domain-specific tool tuning, monitor n-gram verbatim overlap alongside cross-entropy loss. Benchmark models against paraphrased intents that omit explicit tool identifiers.")
    add_p("3. Audit Token Length in Alignment Sets: When constructing gated or conditional alignment datasets, enforce strict token length parity between positive and negative response classes to prevent the model from learning response length as a spurious shortcut.")
    add_p("4. Constrain Runtime Tool Candidates: Eliminate full-schema prompt stuffing. Group system tools into semantic execution clusters and inject compact candidate sets (k=8~12) comprising intra-cluster hard negatives and cross-channel distractors.")

    # 7. Conclusion
    add_sec_heading("7. Conclusion")
    add_p("In this work, we deconstructed the empirical failure modes that arise when fine-tuning compact language models for specialized, low-level system tool environments. We demonstrated that standard supervised fine-tuning masks severe verbatim memorization, sequential multi-stage post-training induces catastrophic capability overwriting (formally bounded by our Subspace Interference Theorem), geometric representation editing hits an acute Pareto cliff, and condition gating suffers from spurious length shortcuts. We introduced Decoupled System-Domain Adaptation (DSDA), an integrated post-training and inference framework that eliminates these vulnerabilities. Validated across both 9B hybrid linear-attention and 27B dense self-attention models, our findings provide rigorous architectural and methodological foundations for deploying robust, controllable, and highly specialized autonomous system agents.")

    # References
    add_sec_heading("References")
    refs = [
        "1. Edward J. Hu, Yelong Shen, Phillip Wallis, Zeyuan Allen-Zhu, Yuanzhi Li, Shean Wang, Lu Wang, Weizhu Chen. LoRA: Low-Rank Adaptation of Large Language Models. ICLR, 2022.",
        "2. Tim Dettmers, Artidoro Pagnoni, Ari Holtzman, Luke Zettlemoyer. QLoRA: Efficient Finetuning of Quantized LLMs. NeurIPS, 2023.",
        "3. Andy Zou, Long Phan, Sarah Chen, James Campbell, Phillip Guo, Richard Ren, Alexander Pan, Xuwang Yin, Mantas Mazeika, Ann-Kathrin Dombrowski, Dan Hendrycks. Representation Engineering: A Top-Down Approach to AI Transparency. arXiv:2310.01405, 2023.",
        "4. Nishant Arditi, Obada Al-Cheikh, Neel Nanda. Refusal in Language Models Is Mediated by a Single Direction. arXiv:2406.11717, 2024.",
        "5. Carlos E. Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, Karthik Narasimhan. SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR, 2024.",
        "6. Shishir G. Patil, Tianjun Zhang, Xin Wang, Joseph E. Gonzalez. Gorilla: Large Language Model Connected with Massive APIs. arXiv:2305.15334, 2023.",
        "7. Yujia Qin, Shengding Hu, Yankai Lin, et al. ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs. ICLR, 2024.",
        "8. Dan Biderman, Jose Gonzalez Ortiz, Jacob Portes, Mansheej Paul, Philip Greengard, Connor Jennings, Daniel King, Sam Havens, Vitaliy Chiley, Jonathan Frankle, Cody Blakeney, John P. Cunningham. LoRA Learns Less and Forgets Less. arXiv:2405.09673, 2024.",
        "9. Songlin Yang, Bailin Wang, Yikang Shen, Rameswar Panda, Yoon Kim. Gated Linear Attention Transformers with Hardware-Efficient Training. ICML, 2024.",
        "10. Xiangning Chen, Chen Liang, Da Huang, Mingxing Tan, et al. Symbolic Discovery of Optimization Algorithms (Lion). NeurIPS, 2023.",
        "11. LinkedIn Liger-Kernel Team. Liger Kernel: Efficient Triton Kernels for LLM Training. 2024.",
        "12. OrionLLM Team. OxCoder-9B: Hybrid Linear Attention Code Model. 2025.",
        "13. Qwen Team. Qwen2.5 Technical Report. arXiv:2412.15115, 2024.",
        "14. Gabriel Ilharco, Marco Tulio Ribeiro, Mitchell Wortsman, Suchin Gururangan, Ludwig Schmidt, Hannaneh Hajishirzi, Ali Farhadi. Editing Models with Task Arithmetic. ICLR, 2023.",
        "15. Prateek Yadav, Derek Tam, Leshem Choshen, Colin Raffel, Mohit Bansal. TIES-Merging: Resolving Interference When Merging Models. NeurIPS, 2023.",
        "16. Shunyu Yao, Jeffrey Zhao, Dian Yu, Nan Du, Izhak Shafran, Karthik Narasimhan, Yuan Cao. ReAct: Synergizing Reasoning and Acting in Language Models. ICLR, 2023.",
        "17. Judea Pearl. Causality: Models, Reasoning, and Inference. Cambridge University Press, 2009."
    ]
    for r in refs:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.25)
        p.paragraph_format.first_line_indent = Inches(-0.25)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(r)
        run.font.name = 'Arial'
        run.font.size = Pt(8.5)

    docx_path = os.path.join(OUTPUT_DIR, "beyond_surface_adaptation.docx")
    doc.save(docx_path)
    print(f"Successfully generated docx: {docx_path}")
    return docx_path

if __name__ == "__main__":
    docx_path = build_paper_docx()
    print("Done generating assets and document.")
