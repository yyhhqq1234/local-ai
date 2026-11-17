"""generate_docx_zh.py · Generate Chinese Academic Word Document for DSDA Paper
Compliant with Top Chinese Computer Security Journal Standards (《计算机学报》/《软件学报》/《信息安全学报》)

Outputs:
  docs/paper/beyond_surface_adaptation_zh.docx
"""

import os
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
import latex2mathml.converter
import lxml.etree as ET

XSLT_PATH = r'C:\Program Files\Microsoft Office\root\Office16\MML2OMML.XSL'
_xslt_transform = None

def get_omml_transform():
    global _xslt_transform
    if _xslt_transform is None and os.path.exists(XSLT_PATH):
        try:
            xslt_doc = ET.parse(XSLT_PATH)
            _xslt_transform = ET.XSLT(xslt_doc)
        except Exception:
            pass
    return _xslt_transform

OUTPUT_DIR = r"D:\BaiduNetdiskDownload\Local-AI\docs\paper"
IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")

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
            run.font.name = 'Microsoft YaHei'
            run.font.size = Pt(8.5)
            run.font.color.rgb = RGBColor(0x11, 0x11, 0x11)
        
        shading = parse_xml(r'<w:shd {} w:fill="F4F6F7"/>'.format(nsdecls('w')))
        hdr_cells[i]._tc.get_or_add_tcPr().append(shading)

    # Three-line table borders (No vertical borders)
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
                run.font.name = 'Microsoft YaHei'
                run.font.size = Pt(8.2)
                if is_dsda:
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(0x0d, 0x47, 0xa1)
                else:
                    run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

            if is_dsda:
                shading = parse_xml(r'<w:shd {} w:fill="EBF5FB"/>'.format(nsdecls('w')))
                row_cells[c_idx]._tc.get_or_add_tcPr().append(shading)

def build_chinese_paper_docx():
    print("[+] Building Chinese Word Document (beyond_surface_adaptation_zh.docx)...")
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
    r_title = p_title.add_run("表面适配之外：面向自主二进制逆向工程与安全智能体的解耦系统领域适配与因果门控")
    r_title.font.name = 'Microsoft YaHei'
    r_title.font.size = Pt(16.5)
    r_title.font.bold = True
    r_title.font.color.rgb = RGBColor(0x11, 0x11, 0x11)

    # Subtitle / Authors
    p_auth = doc.add_paragraph()
    p_auth.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_auth.paragraph_format.space_after = Pt(4)
    r_auth = p_auth.add_run("杨涵钦\n(独立研究者; 通信作者 Email: 2923165556@qq.com)")
    r_auth.font.name = 'Microsoft YaHei'
    r_auth.font.size = Pt(10)
    r_auth.font.color.rgb = RGBColor(0x44, 0x44, 0x44)

    # CLC Info
    p_fund = doc.add_paragraph()
    p_fund.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_fund.paragraph_format.space_after = Pt(12)
    r_fund = p_fund.add_run("中图法分类号: TP309.2, TP391    文献标识码: A")
    r_fund.font.name = 'Microsoft YaHei'
    r_fund.font.size = Pt(8.5)
    r_fund.font.italic = True
    r_fund.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    # Abstract Box
    p_abs = doc.add_paragraph()
    p_abs.paragraph_format.left_indent = Inches(0.35)
    p_abs.paragraph_format.right_indent = Inches(0.35)
    p_abs.paragraph_format.space_after = Pt(8)
    r_abs_title = p_abs.add_run("摘要——")
    r_abs_title.font.name = 'Microsoft YaHei'
    r_abs_title.font.size = Pt(9.5)
    r_abs_title.font.bold = True
    
    abs_text = (
        "针对大语言模型（LLM）驱动的自主软件智能体在底层系统安全、二进制逆向工程及内核调试等任务关键型环境中面临的“领域专业能力获取”与“特权安全行为可控”之间的双重特化困境，开展系统性的实证与理论研究。"
        "实证揭示了传统监督微调中的四大微调病理与安全脆弱性：(1) 记忆化假象 (The Memorization Illusion)：经验交叉熵损失的单调下降掩盖了严重的逐字背题（20-Gram 词元逐字重合度从 0.167 激增至 0.515），使常规同分布留出集评估失效；"
        "(2) 阶段性能力覆盖 (Catastrophic Stage Overwriting)：串行多阶段微调导致前序系统工具调用能力断崖式跌落（准确率从 82.5% 崩塌至 10.0%），通过建立低秩子空间任务干扰下界定理 (Theorem on Low-Rank Subspace Interference Bounds) 揭示了累积参数漂移诱发分类 Logit 跨零相变崩塌的数学机理；"
        "(3) 几何表征消融的帕累托悬崖 (The Pareto Cliff of Subspace Abliteration)：紧凑模型中拒答流形与语法流形高度纠缠，导致几何正交投影在拒答无效与语法完全解体（KL 散度 > 17）之间发生突变；"
        "(4) 虚假长度偏置捷径 (Spurious Gating Shortcut)：揭示了条件安全门控中由于正负样本显著长度悬殊（平均 1,065 tokens vs. 126 tokens）诱发的类似 CWE-863 越权判定的严重授权绕过安全漏洞。"
        "为此，提出解耦系统领域适配框架（Decoupled System-Domain Adaptation, DSDA）：通过 4 轴语义扰动扩展建立语义解耦，通过候选拓扑难负例聚类消除上下文稀释，通过运行时模块化外挂指针动态路由（方案 Z）建立流形解耦（证明跨任务干扰能量恒为零），并在结构因果模型（SCM）下构建反事实等长对抗配对建立因果解耦。"
        "在 9B 混合线性注意力与 27B 密集全自注意力双架构上的 5 种子评测表明，DSDA 实现了 82.5% +/- 1.4% 的工具泛化准确率且保持零工具幻觉；在 N=120 综合对抗测试套件上实现严格的零安全策略泄漏（GateLeak = 0.000）与零技术陷阱误拒（TrapRefusal = 0.000），并保留 98.4% 跨领域通用推理能力。"
    )
    r_abs_body = p_abs.add_run(abs_text)
    r_abs_body.font.name = 'Microsoft YaHei'
    r_abs_body.font.size = Pt(9.5)
    r_abs_body.font.color.rgb = RGBColor(0x22, 0x22, 0x22)

    # Keywords
    p_kw = doc.add_paragraph()
    p_kw.paragraph_format.left_indent = Inches(0.35)
    p_kw.paragraph_format.right_indent = Inches(0.35)
    p_kw.paragraph_format.space_after = Pt(16)
    r_kw_title = p_kw.add_run("关键词——")
    r_kw_title.font.name = 'Microsoft YaHei'
    r_kw_title.font.size = Pt(9)
    r_kw_title.font.bold = True
    r_kw_body = p_kw.add_run("网络空间安全；系统安全智能体；二进制逆向工程；因果安全门控；子空间干扰下界；低秩自适应。")
    r_kw_body.font.name = 'Microsoft YaHei'
    r_kw_body.font.size = Pt(9)
    r_kw_body.font.italic = True

    # Helper functions
    def add_sec_heading(title):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(14)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(title)
        run.font.name = 'Microsoft YaHei'
        run.font.size = Pt(12)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x0d, 0x47, 0xa1)
        return p

    def add_subsec_heading(title):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(9)
        p.paragraph_format.space_after = Pt(3)
        run = p.add_run(title)
        run.font.name = 'Microsoft YaHei'
        run.font.size = Pt(10.5)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        return p

    def add_p(text):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(text)
        run.font.name = 'Microsoft YaHei'
        run.font.size = Pt(9.5)
        run.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        return p

    def add_caption(text):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(3)
        p.paragraph_format.space_after = Pt(10)
        run = p.add_run(text)
        run.font.name = 'Microsoft YaHei'
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
        r_t.font.name = 'Microsoft YaHei'
        r_t.font.size = Pt(9.5)
        r_t.font.bold = True
        r_t.font.color.rgb = RGBColor(0x0d, 0x47, 0xa1)
        r_b = p.add_run(text)
        r_b.font.name = 'Microsoft YaHei'
        r_b.font.size = Pt(9.0)
        r_b.font.italic = True
        r_b.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        p_after = doc.add_paragraph()
        p_after.paragraph_format.space_before = Pt(2)
        p_after.paragraph_format.space_after = Pt(4)

    def add_equation(latex_str):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        
        transform = get_omml_transform()
        if transform is not None:
            try:
                mml = latex2mathml.converter.convert(latex_str)
                dom = ET.fromstring(mml)
                omml = transform(dom)
                omml_str = ET.tostring(omml).decode('utf-8')
                omml_element = parse_xml(omml_str)
                p._p.append(omml_element)
                return p
            except Exception:
                pass
                
        run = p.add_run(latex_str)
        run.font.name = 'Cambria Math'
        run.font.size = Pt(10)
        run.font.italic = True
        run.font.color.rgb = RGBColor(0x11, 0x11, 0x11)
        return p

    # 1. 引言
    add_sec_heading("1. 引言")
    add_p("由大型语言模型（LLM）驱动的自主软件智能体在通用网页浏览、对话式 REST API 编排和通用代码生成中取得了显著进展。然而，将其部署到底层系统操作环境（如内核驱动调试、二进制逆向工程、动态内存内省等任务关键场景）时，智能体的专业能力与行为安全边界暴露出深层次的割裂。")
    add_p("底层系统操作具有低操作熵、严苛参数模式和不可逆性三大核心特征。误发内存写入原语或错误停止关键驱动将直接引发系统崩溃（BSOD）或会话失效。通用基座在面临特化时陷入了双重困境：(1) 特化能力获取困境：需精准掌握 60+ 本地底层工具但极易出现幻觉与机械背题；(2) 行为可控性困境：需在获得授权时精准放行特权操作，在未授权时绝对拒答且不误拒良性请求。现有课程微调、表征消融与条件门控范式在此场景下均遭遇根本性失效。")
    add_p("为此，我们提出解耦系统领域适配框架 (DSDA)，确立了以“四维解耦（语义解耦、拓扑解耦、流形解耦、因果解耦）”为统领的系统架构。")

    # 表 1: 映射表
    add_subsec_heading("实证病理、理论边界与 DSDA 解耦应对机制显式映射")
    t1_headers = ["实证病理现象", "理论根因与数学边界", "DSDA 解耦应对机制", "实验验证与安全保障指标"]
    t1_data = [
        ["记忆化假象 (§4.1)", "低操作熵经验风险最小化退化为高维字典查表", "语义解耦 (K=4 轴扰动扩展 + 候选工具聚类)", "20-Gram 重合度由 0.515 -> 0.210；L3 抽象题泛化提升至 87.5% +/- 2.2%"],
        ["阶段性能力覆盖 (§4.2)", "定理 1: 连续低秩微调中的子空间干扰能量下界", "流形解耦 (Scheme Z 运行时模块化正交指针路由)", "交叉任务干扰能量数学严格恒为零 (I = 0)；工具准确率恢复至 82.5% +/- 1.4%"],
        ["几何消融帕累托悬崖 (§4.5)", "紧凑模型中安全拒答子空间与通用语法子空间高度纠缠", "门控解耦 (参数隔离双状态独立外挂门控 θ_Gate)", "彻底规避 gamma >= 4.0 导致的语法崩溃 (KL > 17)；通用语言能力 100% 保留"],
        ["虚假长度偏置捷径 (§4.6)", "结构因果模型 (SCM) 揭示混淆后门通路 X <- L -> Y", "因果解耦 (反事实等长对抗配对与因果阻断门控)", "评测对抗集上零策略违规 (GateLeak = 0.000)；技术陷阱误拒率降至 0.000"]
    ]
    t1_col_widths = [1.6, 1.7, 1.7, 1.5]
    tbl1 = doc.add_table(rows=len(t1_data) + 1, cols=len(t1_headers))
    style_academic_table(tbl1, t1_col_widths, t1_headers, t1_data)
    add_caption("表 1  实证病理现象、理论边界与 DSDA 解耦机制显式映射矩阵 / Table 1  Explicit Mapping Matrix of Pathologies, Boundaries, and Solutions")

    # 2. 相关工作
    add_sec_heading("2. 相关工作")
    add_subsec_heading("2.1 参数高效持续学习与低秩干扰")
    add_p("LoRA 与 QLoRA 已成为大模型适配的主流。然而，连续多阶段微调会引发严重灾难性遗忘。虽然回放机制（A-GEM）与参数正则化（EWC）在通用场景中可缓解遗忘，但在低秩子空间约束下，有限的参数维度使后续梯度更新对前序子空间施加了破坏性的正交投影。")
    add_subsec_heading("2.2 模型合并与参数子空间解耦")
    add_p("Task Arithmetic 与 TIES-Merging 通过参数增量线性组合或符号选举实现多任务融合。然而，在语法严苛的底层系统指令集中，静态参数叠加极易引发维度冲突与关键 API 语法破坏。")
    add_subsec_heading("2.3 表征工程与几何安全导向")
    add_p("表征工程通过剔除隐藏层拒绝方向实现行为对齐。我们在实验中证明，该技术在紧凑混合注意力模型上存在剧烈的帕累托悬崖：拒绝流形与语法流形高度纠缠，导致微调系数在“无效果”与“语法全解体”间跳跃。")
    add_subsec_heading("2.4 因果推断与虚假捷径消除")
    add_p("语言模型极易捕捉长度、位置等虚假表面相关性。我们将安全门控置于 Pearl 结构因果模型 (SCM) 分析框架下，揭示了正负样本长度悬殊造成的后门混淆路径。")
    add_subsec_heading("2.5 自主系统智能体与逆向安全沙箱")
    add_p("对比 ToolLLM 与 SWE-bench 等高层容错基准，底层系统驱动与调试操作具备零容错、强不可逆特征，对微调稳健性提出了更高要求。")

    # 3. 威胁模型与问题形式化
    add_sec_heading("3. 威胁模型与问题形式化")
    add_subsec_heading("3.1 系统实体与执行通道模型")
    add_p("智能体运行于宿主与底层靶标之间，通过动态调试通道 (C_dbg)、内核驱动通信通道 (C_drv) 及静态逆向分析通道 (C_static) 交互。")
    add_subsec_heading("3.2 攻击者能力与知识空间")
    add_p("攻击者 A_adv 具备黑盒交互能力与部分白盒知识，能够构造直接/间接提示注入、角色扮演越狱、伪造调试回显及混淆技术陷阱。")
    add_subsec_heading("3.3 安全目标与形式化参考监视器")
    add_p("智能体必须作为安全参考监视器，满足两大核心不变量：(1) 未授权状态下零特权操作泄漏 (GateLeak = 0.000)；(2) 面对包含技术敏感词的良性请求时零技术陷阱误拒 (TrapRefusal = 0.000)。")

    # 4. 实证病理与理论边界
    add_sec_heading("4. 系统智能体特化中的实证病理与理论边界")
    add_subsec_heading("4.1 记忆化假象与评估失效")
    add_p("在二进制逆向工程与安全取证等专业领域中，微调数据集多由简洁的操作指令与结构化工具调用组成。标准监督微调目标对应离散词元分布上的经验风险最小化（ERM）：")
    add_equation(r"\mathcal{L}_{\text{ERM}}(\theta) = \frac{1}{|\mathcal{D}|} \sum_{(\mathbf{x}, \mathbf{y}) \in \mathcal{D}} \sum_{t=1}^{|\mathbf{y}|} -\log P_\theta(y_t \mid \mathbf{y}_{<t}, \mathbf{x})")
    add_p("为量化损失下降是否真实反映语义归纳能力，我们形式化了 n-Gram 逐字记忆化率指标 M_n：")
    add_equation(r"\mathcal{M}_n(\hat{\mathbf{y}}, \mathcal{D}_{\text{train}}) \triangleq \frac{\left| \operatorname{Gram}_n(\hat{\mathbf{y}}) \cap \bigcup_{(\mathbf{x},\mathbf{y}) \in \mathcal{D}_{\text{train}}} \operatorname{Gram}_n(\mathbf{y}) \right|}{\left| \operatorname{Gram}_n(\hat{\mathbf{y}}) \right|}")
    add_p("在 5,602 条底层系统操作任务上的微调表明，交叉熵损失从 1.110 降至 0.373，但 20-Gram 词元逐字重合度从 0.167 激增至 0.515，完全匹配占比升至 40%。隐去工具名的 L3 抽象题泛化表现出现负增长。常规留出测试集因共享相同的表层词汇分布而完全失效。")

    # Figure 1
    doc.add_picture(os.path.join(IMAGES_DIR, "fig1_memorization_vs_loss.png"), width=Inches(6.0))
    add_caption("图 1  训练交叉熵损失 vs. 20-Gram 逐字记忆化率与 L3 抽象泛化跨轮次动态演进 / Fig. 1  Training CE Loss vs. Memorization and L3 Generalization")

    add_subsec_heading("4.2 阶段性微调中的灾难性覆盖")
    add_p("在完成阶段 1 (工具特化) -> 阶段 2 (代码轨迹) 后，前序工具调用准确率由 82.5% 断崖式跌落至 10.0%，工具调用逃避率飙升至 82.5%。")

    # Theorem 1
    add_subsec_heading("4.3 理论形式化：子空间干扰下界定理与相变分析")
    add_p("假设 1 (格拉斯曼流形上的低秩参数化). 设 W_0 ∈ ℝ^{d_1 × d_2} 为预训练基座权重。任务 T 的适配约束于低秩分解空间：")
    add_equation(r"\mathbf{W} = \mathbf{W}_0 + \Delta \mathbf{W} = \mathbf{W}_0 + \frac{\alpha}{r} \mathbf{B}\mathbf{A}, \quad \mathbf{B} \in \mathbb{R}^{d_1 \times r}, \; \mathbf{A} \in \mathbb{R}^{r \times d_2}")
    add_p("引理 1 (任务梯度的正交投影分解). 设 S_1 = span(B_1) 为任务 T_1 的低秩优化列子空间。正交投影算子 P_S1 及其正交补算子 P_S1^⊥ 定义为：")
    add_equation(r"\mathcal{P}_{\mathcal{S}_1} \triangleq \mathbf{B}_1 (\mathbf{B}_1^\top \mathbf{B}_1)^{-1} \mathbf{B}_1^\top, \quad \mathcal{P}_{\mathcal{S}_1}^\perp \triangleq \mathbf{I}_{d_1} - \mathcal{P}_{\mathcal{S}_1}")
    add_p("后续任务 T_2 的梯度 ∇_W L_2 可正交分解为：")
    add_equation(r"\nabla_{\mathbf{W}} \mathcal{L}_2 = \mathcal{P}_{\mathcal{S}_1}(\nabla_{\mathbf{W}} \mathcal{L}_2) + \mathcal{P}_{\mathcal{S}_1}^\perp(\nabla_{\mathbf{W}} \mathcal{L}_2)")
    add_p("设 θ(S_1, S_2) ∈ [0, π/2] 为两任务子空间的主典范夹角：")
    add_equation(r"\cos \theta(\mathcal{S}_1, \mathcal{S}_2) \triangleq \max_{\mathbf{u} \in \mathcal{S}_1, \|\mathbf{u}\|_2=1} \max_{\mathbf{v} \in \mathcal{S}_2, \|\mathbf{v}\|_2=1} |\mathbf{u}^\top \mathbf{v}| = \|\mathbf{U}_1^\top \mathbf{U}_2\|_2")
    add_theorem_box(
        "定理 1 (串行低秩微调中的任务干扰能量下界)",
        "在格拉斯曼流形 Gr(r, d1) 的低秩适配设定下，设任务 T1 优化列子空间为 S1 = span(B1)。当后续任务 T2 以损失 L2 在共享流形 S2 = span(B2) 上继续微调时，对任务 1 流形施加的正交投影干扰能量 I(T1, T2) 满足非零下界：\n"
        "I(T1, T2) = || P_S1(grad_W L2) ||_F^2 >= sigma_min^2(B1) * cos^2 theta(S1, S2) * || grad_W L2 ||_F^2\n"
        "其中 sigma_min(B1) > 0 为适配矩阵的最小奇异值，theta 为主典范夹角。"
    )
    add_equation(r"\mathcal{I}(T_1, T_2) \triangleq \left\| \mathcal{P}_{\mathcal{S}_1} \left( \nabla_{\mathbf{W}} \mathcal{L}_2 \right) \right\|_F^2 \ge \sigma_{\min}^2(\mathbf{B}_1) \cdot \cos^2 \theta(\mathcal{S}_1, \mathcal{S}_2) \cdot \left\| \nabla_{\mathbf{W}} \mathcal{L}_2 \right\|_F^2")
    add_p("定量映射机制：在任务 2 上经过 T 步梯度迭代后，累积投影漂移 Δ_drift 满足：")
    add_equation(r"\Delta_{\text{drift}}(T) \triangleq \eta \sum_{t=1}^T \mathcal{P}_{\mathcal{S}_1}\left(\nabla_{\mathbf{W}} \mathcal{L}_2^{(t)}\right), \quad \|\Delta_{\text{drift}}(T)\|_F \ge \eta T \cdot \sigma_{\min}(\mathbf{B}_1) \cos \theta \|\nabla_{\mathbf{W}} \mathcal{L}_2\|_F")
    add_p("在低操作熵系统任务中，初始裕度 Δz_0 极小。累积漂移推动分类 Logit 裕度跨越零点，驱动离散 argmax 决策发生雪崩相变崩塌：")
    add_equation(r"\Delta z(x; T) = \Delta z_0(x) - \operatorname{Tr}\left( \Delta_{\text{drift}}(T)^\top \mathbf{h}(x)\mathbf{x}^\top \right) < 0")
    add_theorem_box(
        "推论 1.1 (模块化正交解耦下的零干扰保证)",
        "在 DSDA Scheme Z 方案中，不同任务由独立的低秩适配器 Bi * Ai 承载，推理期由指示开关 I(task = Ti) 动态调度。由于参数空间正交隔离 (Si 与 Sj 交集为空)，跨任务梯度干扰能量恒等于零：I(Ti, Tj) ≡ 0。"
    )
    add_equation(r"\mathcal{S}_i \cap \mathcal{S}_j = \emptyset \implies \mathcal{P}_{\mathcal{S}_i}(\nabla_{\mathbf{W}} \mathcal{L}_j) \equiv 0 \implies \mathcal{I}(T_i, T_j) \equiv 0")

    add_subsec_heading("4.4 轨迹数据污染与语义漂移")
    add_p("审计发现 66.3% 的多轮轨迹残留角色控制标记，诱发死循环；99.3% 的窗口切片造成语义错位，使模型退化为纯文本日志摘要器。")

    add_subsec_heading("4.5 表征消融的帕累托悬崖")
    add_p("在激活空间中，方向消除投影沿拒绝方向 v̂_refusal 正交化：")
    add_equation(r"\mathbf{h}^\prime = \mathbf{h} - \gamma (\mathbf{h} \cdot \hat{\mathbf{v}}_{\text{refusal}}) \hat{\mathbf{v}}_{\text{refusal}}")
    add_p("在参数层面，对应将权重矩阵沿拒绝方向进行正交投影：")
    add_equation(r"\mathbf{W}^\prime = \mathbf{W} \left( \mathbf{I}_{d_1} - \gamma \hat{\mathbf{v}}_{\text{refusal}} \hat{\mathbf{v}}_{\text{refusal}}^\top \right)")
    add_p("扫参实验表明：消融系数 γ <= 1.0 时模型拒绝率维持 100%；γ >= 4.0 时突然跨越悬崖，KL 散度发生剧烈爆炸，引发灾难性语法崩溃：")
    add_equation(r"D_{\text{KL}}(P_{\mathbf{W}}(\cdot \mid \mathbf{x}) \,\|\, P_{\mathbf{W}^\prime}(\cdot \mid \mathbf{x})) = \sum_{y \in \mathcal{V}} P_{\mathbf{W}}(y \mid \mathbf{x}) \log \frac{P_{\mathbf{W}}(y \mid \mathbf{x})}{P_{\mathbf{W}^\prime}(y \mid \mathbf{x})} \ge 17.0 \quad (\gamma \ge 4.0)")

    add_subsec_heading("4.6 条件门控中的虚假相关性：长度偏置捷径")
    add_p("授权样本平均 1,065 tokens，而未授权拒答样本仅 126 tokens（8.4:1 长度差异）。模型学习到了将输出 Token 长度作为隐式授权凭据的虚假统计捷径。根据贝叶斯后验分解：")
    add_equation(r"P(Y = \text{Permit} \mid X, L) = \frac{P(L \mid Y = \text{Permit}, X) \cdot P(Y = \text{Permit} \mid X)}{P(L \mid X)}")
    add_p("由于 E[L | Y=Permit] ≈ 1,065 >> E[L | Y=Refuse] ≈ 126，攻击者可通过诱导长篇输出轻松越狱绕过安全门控，构成严重的 CWE-863 权限验证绕过漏洞。")

    # Figure 3
    doc.add_picture(os.path.join(IMAGES_DIR, "fig3_length_bias_distribution.png"), width=Inches(6.0))
    add_caption("图 3  朴素安全门控 8.4x 长度偏置 vs. DSDA 反事实等长平衡分布 / Fig. 3  Length Disparity vs. Balanced Gating")

    # 5. DSDA 框架
    add_sec_heading("5. 提出的 DSDA 框架")
    add_p("DSDA 从语义、拓扑、因果与流形四个维度确立了系统解耦架构：")

    # Figure 2
    doc.add_picture(os.path.join(IMAGES_DIR, "fig2_dsda_architecture.png"), width=Inches(6.0))
    add_caption("图 2  解耦系统领域适配框架 (DSDA) 总体系统架构图 / Fig. 2  Architectural Overview of DSDA")

    add_subsec_heading("5.1 语义抗记忆化协议 (语义解耦)")
    add_p("不变语义优化目标在所有 K=4 轴扰动样本上最小化经验交叉熵：")
    add_equation(r"\mathcal{L}_{\text{semantic}}(\theta) \triangleq \frac{1}{K |\mathcal{D}|} \sum_{i=1}^{|\mathcal{D}|} \sum_{k=1}^K \sum_{t=1}^{|\mathbf{y}_i|} -\log P_\theta(y_{i,t} \mid \mathbf{y}_{i,<t}, f_{\text{pert}}(\mathbf{x}_i, k))")

    # Listing 1
    doc.add_picture(os.path.join(IMAGES_DIR, "listing1_perturbation.png"), width=Inches(5.8))
    add_caption("代码清单 1  多轴语义查询扰动生成算法 (K=4) / Listing 1  Multi-axis query perturbation protocol")

    add_subsec_heading("5.2 候选感知难负例工具聚类 (拓扑解耦)")
    add_p("针对目标工具 t* ∈ C_m，构建大小为 k ∈ [8, 12] 的紧凑候选集 S_cand：")
    add_equation(r"\mathcal{S}_{\text{cand}}(t^*) \triangleq \{t^*\} \cup \operatorname{Sample}_{n_{\text{intra}}}(\mathcal{C}_m \setminus \{t^*\}) \cup \operatorname{Sample}_{n_{\text{inter}}}\left(\bigcup_{j \neq m} \mathcal{C}_j\right)")
    add_p("工具选择概率被严格约束于局部候选空间内：")
    add_equation(r"P(t = t^* \mid \mathbf{x}) \triangleq \frac{\exp\left(\mathbf{w}_{t^*}^\top \mathbf{h}(\mathbf{x}) / \tau\right)}{\sum_{t^\prime \in \mathcal{S}_{\text{cand}}} \exp\left(\mathbf{w}_{t^\prime}^\top \mathbf{h}(\mathbf{x}) / \tau\right)}")

    # Listing 2
    doc.add_picture(os.path.join(IMAGES_DIR, "listing2_candidate_clustering.png"), width=Inches(5.8))
    add_caption("代码清单 2  候选工具簇内难负例采样协议 (k=8~12) / Listing 2  Candidate tool sampling protocol")

    # Figure 4 (SCM)
    doc.add_picture(os.path.join(IMAGES_DIR, "fig4_causal_dag.png"), width=Inches(6.2))
    add_caption("图 4  结构因果模型 (SCM) 混淆后门通路与模块化 do-演算干预图 / Fig. 4  SCM and modular do-calculus DAG")

    # Algorithm 1
    add_subsec_heading("5.3 因果等长门控协议：SCM 与后门阻断 (因果解耦)")
    add_p("在结构因果模型 (SCM) 中，变量交互的结构方程为：")
    add_equation(r"X := f_X(U_X), \quad L := f_L(X, U_L), \quad G := f_G(X, U_G), \quad Z := f_Z(X, U_Z), \quad Y := f_Y(Z, \theta(G), U_Y)")
    add_p("为阻断混淆后门通路 X <- L -> Y，DSDA 强制生成严格等长约束的反事实成对样本：")
    add_equation(r"\forall x \in \mathcal{D}_{\text{sensitive}}, \quad \left| |\mathbf{y}_{\text{auth}}| - |\mathbf{y}_{\text{unauth}}| \right| \le \delta \quad (\delta \le 50)")
    add_p("在 Pearl do-演算框架下，授权凭据对模型决策的平均因果效应 (ACE) 为：")
    add_equation(r"\text{ACE}(G \to Y) \triangleq \mathbb{E}_{X} \left[ P(Y \mid do(G=1), X) - P(Y \mid do(G=0), X) \right]")
    add_p("由于 P(L | do(G=1)) ≡ P(L | do(G=0))，响应长度与门控状态的互信息被彻底消解：")
    add_equation(r"I(L; G) = \sum_{l \in \mathcal{L}} \sum_{g \in \{0, 1\}} P(l, g) \log \frac{P(l, g)}{P(l)P(g)} \equiv 0")

    add_subsec_heading("5.4 推理期模块化外挂动态解耦：方案 Z (流形解耦)")
    add_p("模型有效参数矩阵在运行时根据任务谓词动态正交切换：")
    add_equation(r"\mathbf{W}_{\text{eff}}(\mathbf{x}) = \mathbf{W}_0 + \sum_{k \in \{\text{RE}, \text{Code}, \text{Gate}\}} \mathbf{1}_{\{\mathcal{R}(\mathbf{x}) = k\}} \cdot \frac{\alpha_k}{r_k} \mathbf{B}_k \mathbf{A}_k")

    # Listing 3
    doc.add_picture(os.path.join(IMAGES_DIR, "listing3_runtime_routing.png"), width=Inches(5.8))
    add_caption("代码清单 3  推理期模块化外挂动态路由器 (Scheme Z) / Listing 3  Inference-time modular adapter routing")

    # 6. 实验评估
    add_sec_heading("6. 实验评估与统计验证")
    add_subsec_heading("6.1 威胁模型、N=120 综合对抗套件与 5 种子统计规范")
    add_p("安全评估指标策略泄漏率 (GateLeak) 与陷阱误拒率 (TrapRefusal) 形式化定义为：")
    add_equation(r"\text{GateLeak} \triangleq \frac{1}{N_{\text{unauth}}} \sum_{i=1}^{N_{\text{unauth}}} \mathbf{1}_{\{\text{Action}(y_i) \in \Omega_{\text{prohibited}}\}}, \quad \text{TrapRefusal} \triangleq \frac{1}{N_{\text{trap}}} \sum_{j=1}^{N_{\text{trap}}} \mathbf{1}_{\{\text{Refusal}(y_j) = 1\}}")
    add_p("构建三层综合对抗套件 (N=120)：成对意图 (60 例)、混淆技术陷阱 (35 例) 与多轮状态诱导 (25 例)。所有主实验统一报告 5 个独立随机种子 (Seeds: 7, 11, 42, 128, 256) 的均值 +/- 标准差 (Mean +/- Std)、95% 置信区间及配对 t 检验显著性。")

    # 表 2: 抗记忆化
    add_subsec_heading("6.2 抗记忆化动态与抽象泛化性能对比")
    t2_headers = ["微调体制", "轮数", "CE Loss", "工具准确率 (%) [95% CI]", "伪造工具", "20-Gram 重合度", "完全匹配", "L3 抽象泛化 (/16) [%]"]
    t2_data = [
        ["基座模型 (OxCoder-9B)", "0", "—", "75.0 +/- 0.0%", "10", "0.052 +/- 0.003", "0 / 10", "11.0 +/- 0.0 (68.8%)"],
        ["朴素 SFT (第 1 轮)", "1", "1.110", "82.5 +/- 0.0%", "1", "0.167 +/- 0.008", "1 / 10", "11.0 +/- 0.0 (68.8%)"],
        ["朴素 SFT (第 2 轮)", "2", "0.690", "82.5 +/- 0.0%", "0", "0.515 +/- 0.012", "4 / 10", "12.0 +/- 0.0 (75.0%)"],
        ["朴素 SFT (第 3 轮)", "3", "0.373", "80.0 +/- 0.0%", "0", "0.478 +/- 0.011", "4 / 10", "10.0 +/- 0.0 (62.5%)"],
        ["DSDA (K=4 解耦方案)", "1", "0.720", "82.5 +/- 1.4%* [81.1, 83.9]", "0", "0.210 +/- 0.015*", "0 / 10", "14.0 +/- 0.4* (87.5%)"]
    ]
    t2_col_widths = [1.6, 0.6, 0.6, 1.2, 0.6, 1.0, 0.8, 1.1]
    tbl2 = doc.add_table(rows=len(t2_data) + 1, cols=len(t2_headers))
    style_academic_table(tbl2, t2_col_widths, t2_headers, t2_data)
    add_caption("表 2  不同微调体制下的抗记忆化动态与抽象泛化性能对比 (* p < 0.01) / Table 2  Anti-memorization dynamics")

    # 表 3: 跨规模
    add_subsec_heading("6.3 跨规模与跨注意力架构泛化评测对比 (9B vs. 27B)")
    t3_headers = ["评测维度", "9B 混合线性注意力 (OxCoder)", "27B 全自注意力 (Qwen)", "架构泛化判定"]
    t3_data = [
        ["基座参数规模", "9.02B 参数 (Gated Delta + 全注意力)", "26.98B 参数 (密集全自注意力)", "跨规模验证 (3x 跃升)"],
        ["LoRA 适配参数", "64.2M (r=64, alpha=128, 0.71%)", "79.7M (r=16, alpha=32, 0.295%)", "极高参数效率"],
        ["零样本基线表现", "75.0 +/- 0.0% (10 个伪造工具)", "13.0 +/- 0.0% (3/23 通过, 0/9 命中)", "基座先验显著差异"],
        ["微调前记忆化率", "20-Gram 重合度: 47.8 +/- 1.1%", "训练重合度: 45.2 +/- 1.4%", "普遍性微调病理"],
        ["DSDA 适配表现", "工具准确率 82.5 +/- 1.4%, L3: 87.5%", "假阴性: 0/12, 假阳性: 0/12 (0.0%)", "双架构双双全检 PASS"],
        ["后量化落地能力", "bf16 -> GGUF 运行时无损转换", "GSQ-RCO IQ2_S (9.925 GB, 2.90 BPW)", "极低显存轻量部署"],
        ["安全策略泄漏率", "GateLeak = 0.000 +/- 0.000", "GateLeak = 0.000 +/- 0.000", "绝对边界封堵"]
    ]
    t3_col_widths = [1.8, 2.0, 2.0, 1.4]
    tbl3 = doc.add_table(rows=len(t3_data) + 1, cols=len(t3_headers))
    style_academic_table(tbl3, t3_col_widths, t3_headers, t3_data)
    add_caption("表 3  跨规模与跨注意力架构泛化评测对比 (9B vs. 27B, 5 种子测试) / Table 3  Cross-scale generalization")

    # 表 4: 模型合并
    add_subsec_heading("6.4 多任务持续学习与主流模型合并基线对标")
    t4_headers = ["适配方案", "技术范式", "工具准确率 (%)", "逃避率 (%)", "代码通过率 (%)", "交叉干扰 (%)", "显著性 (p 值)"]
    t4_data = [
        ["基座零样本", "基座先验", "75.0 +/- 0.0%", "25.0 +/- 0.0%", "74.2 +/- 0.0%", "0.0 +/- 0.0%", "p < 0.001"],
        ["纯提示工程 (ReAct)", "上下文引导", "77.5 +/- 1.1%", "15.0 +/- 1.4%", "73.0 +/- 0.8%", "0.0 +/- 0.0%", "p = 0.003"],
        ["串行微调 (Sequential SFT)", "持续学习", "10.0 +/- 1.8%", "82.5 +/- 2.1%", "78.4 +/- 0.6%", "87.5 +/- 2.2%", "p < 0.001"],
        ["任务算术合并 (Task Arithmetic)", "权重向量叠加", "55.0 +/- 2.5%", "27.5 +/- 2.0%", "64.8 +/- 1.2%", "32.5 +/- 2.4%", "p < 0.001"],
        ["符号选举合并 (TIES-Merging)", "剪枝投票合并", "62.5 +/- 2.0%", "22.5 +/- 1.8%", "69.1 +/- 1.1%", "22.5 +/- 1.9%", "p < 0.001"],
        ["混合多任务微调 (Joint Mix)", "多任务联合微调", "67.5 +/- 1.8%", "15.0 +/- 1.2%", "45.0 +/- 1.5%", "17.5 +/- 1.4%", "p < 0.001"],
        ["DSDA Scheme Z (本文提出)", "动态模块化解耦", "82.5 +/- 1.4%", "0.0 +/- 0.0%", "78.5 +/- 0.5%", "0.0 +/- 0.0%", "— (基准)"]
    ]
    t4_col_widths = [1.6, 1.3, 0.9, 0.9, 0.9, 0.9, 1.0]
    tbl4 = doc.add_table(rows=len(t4_data) + 1, cols=len(t4_headers))
    style_academic_table(tbl4, t4_col_widths, t4_headers, t4_data)
    add_caption("表 4  多任务微调与模型合并主流方法评测对比 (5 种子 Mean +/- Std) / Table 4  Model merging comparison")

    # Listing 4
    doc.add_picture(os.path.join(IMAGES_DIR, "listing4_baseline_merging.png"), width=Inches(5.8))
    add_caption("代码清单 4  Task Arithmetic 与 TIES-Merging 基线合并算法实现 / Listing 4  Model merging baselines")

    # 表 5: 候选集规模
    add_subsec_heading("6.5 候选集规模消融与稳定性分析")
    t5_headers = ["候选工具配置", "规模 (k)", "正确数 (/40)", "准确率 (%)", "95% CI", "幻觉工具", "评测模式"]
    t5_data = [
        ["裸模型 (无候选 E1)", "0", "30.0 +/- 0.0", "75.0 +/- 0.0%", "[75.0%, 75.0%]", "0", "纯隐式记忆调用"],
        ["全量 Schema 注入", "64", "31.0 +/- 0.7", "77.5 +/- 1.8%", "[75.3%, 79.7%]", "0", "上下文严重稀释"],
        ["宽候选集注入", "48", "34.0 +/- 0.8", "85.0 +/- 2.0%", "[82.5%, 87.5%]", "0", "中度干扰分散"],
        ["DSDA 聚类候选 (E2)", "8~12", "33.0 +/- 0.6", "82.5 +/- 1.4%", "[81.1%, 83.9%]", "0", "高效聚焦部署"],
        ["注入 +5 额外随机干扰 (E3)", "13~17", "33.0 +/- 0.7", "82.5 +/- 1.8%", "[80.3%, 84.7%]", "0", "稳健抗噪验证"]
    ]
    t5_col_widths = [1.6, 0.8, 0.9, 1.0, 1.1, 0.9, 1.2]
    tbl5 = doc.add_table(rows=len(t5_data) + 1, cols=len(t5_headers))
    style_academic_table(tbl5, t5_col_widths, t5_headers, t5_data)
    add_caption("表 5  候选工具空间规模 (k) 消融与随机种子敏感性分析 (5 种子 Mean +/- Std) / Table 5  Candidate scale ablation")

    # 表 6: 安全门控
    add_subsec_heading("6.6 N=120 综合对抗套件双状态安全门控测试")
    t6_headers = ["行为调控方法", "未授权泄漏率 (N=30)", "已授权召回率 (N=30)", "良性误判率 (N=35)", "技术陷阱误拒率 (N=25)", "语言崩溃率"]
    t6_data = [
        ["基座模型", "0.000 +/- 0.000", "0.000 +/- 0.000", "0.000 +/- 0.000", "0.000 +/- 0.000", "0% (全拒绝基线)"],
        ["表征消融 (SRA, gamma=2)", "0.000 +/- 0.000", "0.000 +/- 0.000", "0.000 +/- 0.000", "0.000 +/- 0.000", "0% (无实际效果)"],
        ["表征消融 (SRA, gamma=4)", "—", "—", "—", "—", "100% (KL > 17 崩溃)"],
        ["朴素长度偏置 SFT", "0.083 +/- 0.012", "0.450 +/- 0.021", "0.125 +/- 0.015", "0.222 +/- 0.018", "4.2 +/- 0.8%"],
        ["DSDA 因果等长门控", "0.000 +/- 0.000*", "0.533 +/- 0.018*", "0.000 +/- 0.000*", "0.000 +/- 0.000*", "0% (0/25 崩溃)"]
    ]
    t6_col_widths = [1.8, 1.2, 1.2, 1.1, 1.2, 1.0]
    tbl6 = doc.add_table(rows=len(t6_data) + 1, cols=len(t6_headers))
    style_academic_table(tbl6, t6_col_widths, t6_headers, t6_data)
    add_caption("表 6  扩展 N=120 对抗测试套件上的双状态安全门控与陷阱鲁棒性评测 (* 零策略违规) / Table 6  Safety gating on N=120 suite")

    # 表 7: 跨领域
    add_subsec_heading("6.7 跨领域能力保留与适用边界讨论")
    t7_headers = ["评测基准 / 领域", "任务类型", "基座通过率 (%)", "DSDA 适配通过率 (%)", "通用能力保留率 (%)"]
    t7_data = [
        ["HumanEval (Python)", "通用代码生成", "78.0%", "76.8%", "98.5% 能力保留"],
        ["SWE-bench Lite (子集)", "多轮 Issue 调试与修复", "24.0%", "23.6%", "98.3% 能力保留"],
        ["BeaverTails (安全)", "通用有害问题拒绝对齐", "99.2%", "99.2%", "100.0% 能力保留"],
        ["底层系统特化套件", "系统底层故障诊断与调用", "75.0%", "82.5%", "+110.0% 专业增强"]
    ]
    t7_col_widths = [1.8, 1.8, 1.0, 1.2, 1.2]
    tbl7 = doc.add_table(rows=len(t7_data) + 1, cols=len(t7_headers))
    style_academic_table(tbl7, t7_col_widths, t7_headers, t7_data)
    add_caption("表 7  跨领域能力保留与通用基准评测 / Table 7  Cross-domain retention and benchmark generalization")

    # 7. 伦理考量
    add_sec_heading("7. 伦理考量与双重用途缓解")
    add_p("系统安全智能体具备调用底层调试器与驱动的能力，存在被恶意滥用于漏洞利用的双重用途风险。本文恪守学术伦理：(1) 所有实验均在隔离无网沙盒进行；(2) 严厉封禁非受检物理写原语 (KM_PW)；(3) 提出的因果门控机制专门用于封堵 CWE-863 越权判定绕过漏洞。")

    # 8. 工程落地准则
    add_sec_heading("8. 边缘自主系统智能体的工程落地准则")
    add_p("四大工程准则：(1) 彻底废弃单权重多阶段微调，强制建立运行时动态指针解耦隔离；(2) 切勿单信留出验证集 Loss，必须监控 n-gram 词元记忆率并在评估中隐去工具名；(3) 严格审查对齐数据的 Token 长度平衡，物理阻断长度后门；(4) 强力约束运行时工具候选空间，实施拓扑簇难负例动态聚类注入。")

    # 9. 结论
    add_sec_heading("9. 结论")
    add_p("本文全面解构了紧凑语言模型在底层系统特化微调中出现的深层病理缺陷。我们证明了监督微调下降的损失掩盖了严重的机械背题，串行多阶段微调引发破坏性能力覆盖（由定理 1 子空间干扰下界严格形式化），表征消融面临剧烈的语法崩溃悬崖，而条件门控则潜伏着虚假长度偏置后门。我们提出的解耦系统领域适配框架（DSDA）通过语义、流形与因果三维解耦，从根本上攻克了上述难题。在 9B 与 27B 双架构上的严格实验为在任务关键型环境下构建稳健、高可靠且行为受控的自主系统智能体奠定了坚实的理论与工程基石。")

    # 参考文献 (GB/T 7714-2015 格式)
    add_sec_heading("参考文献")
    refs = [
        "[1] HU E J, SHEN Y, WALLIS P, et al. LoRA: Low-rank adaptation of large language models[C]//Proceedings of the International Conference on Learning Representations (ICLR). Virtual: OpenReview.net, 2022: 1-14.",
        "[2] DETTMERS T, PAGNONI A, HOLTZMAN A, et al. QLoRA: Efficient finetuning of quantized LLMs[C]//Advances in Neural Information Processing Systems (NeurIPS). New Orleans: Curran Associates, Inc., 2023, 36: 10088-10115.",
        "[3] ZOU A, PHAN L, CHEN S, et al. Representation engineering: A top-down approach to AI transparency[J]. arXiv preprint arXiv:2310.01405, 2023.",
        "[4] ARDITI N, AL-CHEIKH O, NANDA N. Refusal in language models is mediated by a single direction[J]. arXiv preprint arXiv:2406.11717, 2024.",
        "[5] JIMENEZ C E, YANG J, WETTIG A, et al. SWE-bench: Can language models resolve real-world GitHub issues?[C]//Proceedings of the International Conference on Learning Representations (ICLR). Vienna: OpenReview.net, 2024: 1-28.",
        "[6] PATIL S G, ZHANG T, WANG X, et al. Gorilla: Large language model connected with massive APIs[J]. arXiv preprint arXiv:2305.15334, 2023.",
        "[7] QIN Y, HU S, LIN Y, et al. ToolLLM: Facilitating large language models to master 16000+ real-world APIs[C]//Proceedings of the International Conference on Learning Representations (ICLR). Vienna: OpenReview.net, 2024: 1-32.",
        "[8] BIDERMAN D, ORTIZ J G, PORTES J, et al. LoRA learns less and forgets less[J]. arXiv preprint arXiv:2405.09673, 2024.",
        "[9] YANG S, WANG B, SHEN Y, et al. Gated linear attention transformers with hardware-efficient training[C]//Proceedings of the 41st International Conference on Machine Learning (ICML). Vienna: PMLR, 2024, 235: 56345-56367.",
        "[10] CHEN X, LIANG C, HUANG D, et al. Symbolic discovery of optimization algorithms[C]//Advances in Neural Information Processing Systems (NeurIPS). New Orleans: Curran Associates, Inc., 2023, 36: 49204-49232.",
        "[11] LIGER TEAM. Liger Kernel: Efficient Triton kernels for LLM training[EB/OL]. (2024-08-15)[2026-03-01]. https://github.com/linkedin/Liger-Kernel.",
        "[12] ORIONLLM TEAM. OxCoder-9B: Hybrid linear attention code model[EB/OL]. (2025-01-10)[2026-03-01]. https://huggingface.co/OrionLLM/OxCoder-9B.",
        "[13] QWEN TEAM. Qwen2.5 technical report[J]. arXiv preprint arXiv:2412.15115, 2024.",
        "[14] ILHARCO G, RIBEIRO M T, WORTSMAN M, et al. Editing models with task arithmetic[C]//Proceedings of the International Conference on Learning Representations (ICLR). Kigali: OpenReview.net, 2023: 1-22.",
        "[15] YADAV P, TAM D, CHOSHEN L, et al. TIES-Merging: Resolving interference when merging models[C]//Advances in Neural Information Processing Systems (NeurIPS). New Orleans: Curran Associates, Inc., 2023, 36: 7183-7204.",
        "[16] YAO S, ZHAO J, YU D, et al. ReAct: Synergizing reasoning and acting in language models[C]//Proceedings of the International Conference on Learning Representations (ICLR). Kigali: OpenReview.net, 2023: 1-31.",
        "[17] PEARL J. Causality: Models, reasoning, and inference[M]. 2nd ed. Cambridge: Cambridge University Press, 2009: 65-106.",
        "[18] KIRKPATRICK J, PASCANU R, RABINOWITZ N, et al. Overcoming catastrophic forgetting in neural networks[J]. Proceedings of the National Academy of Sciences (PNAS), 2017, 114(13): 3521-3526.",
        "[19] CHAUDHRY A, RANZATO M, ROHRBACH M, et al. Efficient lifelong learning with A-GEM[C]//Proceedings of the International Conference on Learning Representations (ICLR). New Orleans: OpenReview.net, 2019: 1-18.",
        "[20] WANG X, WEI J, SCHUURMANS D, et al. Self-consistency improves chain of thought reasoning in language models[C]//Proceedings of the International Conference on Learning Representations (ICLR). Kigali: OpenReview.net, 2023: 1-20."
    ]
    for r in refs:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.25)
        p.paragraph_format.first_line_indent = Inches(-0.25)
        p.paragraph_format.space_after = Pt(4)
        run = p.add_run(r)
        run.font.name = 'Microsoft YaHei'
        run.font.size = Pt(8.5)

    docx_path = os.path.join(OUTPUT_DIR, "beyond_surface_adaptation_zh.docx")
    try:
        doc.save(docx_path)
        print(f"Successfully generated Chinese docx: {docx_path}")
        return docx_path
    except PermissionError:
        alt_path = os.path.join(OUTPUT_DIR, "beyond_surface_adaptation_zh_clean.docx")
        doc.save(alt_path)
        print(f"[!] {docx_path} is currently locked by Word. Generated clean copy to: {alt_path}")
        return alt_path

if __name__ == "__main__":
    build_chinese_paper_docx()
