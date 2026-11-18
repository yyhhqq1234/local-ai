# -*- coding: utf-8 -*-
"""
update_docx_generators.py
Updates generate_docx_zh.py and generate_assets_and_docx.py with the new mathematical theorems,
propositions, corollaries, and SCM formulations.
"""

def update_zh_generator():
    with open('docs/paper/generate_docx_zh.py', 'r', encoding='utf-8') as f:
        code = f.read()

    # 1. Update Table 1 rows
    old_t1_code = """        ["阶段性能力覆盖 (§4.2)", "定理 1: 连续低秩微调中的子空间干扰能量下界", "流形解耦 (Scheme Z 运行时模块化正交指针路由)", "交叉任务干扰能量数学严格恒为零 (I = 0)；工具准确率恢复至 82.5% +/- 1.4%"],
        ["几何消融帕累托悬崖 (§4.5)", "紧凑模型中安全拒答子空间与通用语法子空间高度纠缠", "门控解耦 (参数隔离双状态独立外挂门控 θ_Gate)", "彻底规避 gamma >= 4.0 导致的语法崩溃 (KL > 17)；通用语言能力 100% 保留"],
        ["虚假长度偏置捷径 (§4.6)", "结构因果模型 (SCM) 揭示混淆后门通路 X <- L -> Y", "因果解耦 (反事实等长对抗配对与因果阻断门控)", "评测对抗集上零策略违规 (GateLeak = 0.000)；技术陷阱误拒率降至 0.000"]"""

    new_t1_code = """        ["阶段性能力覆盖 (§4.2)", "定理 1 (子空间与参数干扰双阶下界) 与 命题 1 (相变相坍缩充分条件)", "流形解耦 (Scheme Z 运行时模块化正交指针路由)", "跨任务直接参数干扰数学严格恒为零 (I_param^direct ≡ 0)；工具准确率恢复至 82.5% +/- 1.4% (p < 0.01)"],
        ["几何消融帕累托悬崖 (§4.5)", "紧凑模型中安全拒答子空间与通用语法子空间高度纠缠", "门控解耦 (参数隔离双状态独立外挂门控 θ_Gate)", "彻底规避 gamma >= 4.0 导致的语法崩溃 (KL > 17)；通用语言能力 100% 保留"],
        ["虚假长度偏置捷径 (§4.6)", "结构因果模型 (SCM) 与 命题 2: 长度混淆打开双后门通路", "因果解耦 (反事实等长对抗配对与 KL 不变性门控)", "N=120 对抗套件 0 越权泄露 (95% Wilson CI: [0.00%, 3.10%])；互信息 I(L; Ĝ) ≡ 0"]"""

    assert old_t1_code in code, "old_t1_code not found in generate_docx_zh.py"
    code = code.replace(old_t1_code, new_t1_code)

    # 2. Update Section 4.3 block
    old_sec43 = """    # Theorem 1
    add_subsec_heading("4.3 理论形式化：子空间干扰下界定理与相变分析")
    add_p("假设 1 (格拉斯曼流形上的低秩参数化). 设 W_0 ∈ ℝ^{d_1 × d_2} 为预训练基座权重。任务 T 的适配约束于低秩分解空间：")
    add_equation(r"\\mathbf{W} = \\mathbf{W}_0 + \\Delta \\mathbf{W} = \\mathbf{W}_0 + \\frac{\\alpha}{r} \\mathbf{B}\\mathbf{A}, \\quad \\mathbf{B} \\in \\mathbb{R}^{d_1 \\times r}, \\; \\mathbf{A} \\in \\mathbb{R}^{r \\times d_2}")
    add_p("引理 1 (任务梯度的正交投影分解). 设 S_1 = span(B_1) 为任务 T_1 的低秩优化列子空间。正交投影算子 P_S1 及其正交补算子 P_S1^⊥ 定义为：")
    add_equation(r"\\mathcal{P}_{\\mathcal{S}_1} \\triangleq \\mathbf{B}_1 (\\mathbf{B}_1^\\top \\mathbf{B}_1)^{-1} \\mathbf{B}_1^\\top, \\quad \\mathcal{P}_{\\mathcal{S}_1}^\\perp \\triangleq \\mathbf{I}_{d_1} - \\mathcal{P}_{\\mathcal{S}_1}")
    add_p("后续任务 T_2 的梯度 ∇_W L_2 可正交分解为：")
    add_equation(r"\\nabla_{\\mathbf{W}} \\mathcal{L}_2 = \\mathcal{P}_{\\mathcal{S}_1}(\\nabla_{\\mathbf{W}} \\mathcal{L}_2) + \\mathcal{P}_{\\mathcal{S}_1}^\\perp(\\nabla_{\\mathbf{W}} \\mathcal{L}_2)")
    add_p("设 θ(S_1, S_2) ∈ [0, π/2] 为两任务子空间的主典范夹角：")
    add_equation(r"\\cos \\theta(\\mathcal{S}_1, \\mathcal{S}_2) \\triangleq \\max_{\\mathbf{u} \\in \\mathcal{S}_1, \\|\\mathbf{u}\\|_2=1} \\max_{\\mathbf{v} \\in \\mathcal{S}_2, \\|\\mathbf{v}\\|_2=1} |\\mathbf{u}^\\top \\mathbf{v}| = \\|\\mathbf{U}_1^\\top \\mathbf{U}_2\\|_2")
    add_theorem_box(
        "定理 1 (串行低秩微调中的任务干扰能量下界)",
        "在格拉斯曼流形 Gr(r, d1) 的低秩适配设定下，设任务 T1 优化列子空间为 S1 = span(B1)。当后续任务 T2 以损失 L2 在共享流形 S2 = span(B2) 上继续微调时，对任务 1 流形施加的正交投影干扰能量 I(T1, T2) 满足非零下界：\\n"
        "I(T1, T2) = || P_S1(grad_W L2) ||_F^2 >= sigma_min^2(B1) * cos^2 theta(S1, S2) * || grad_W L2 ||_F^2\\n"
        "其中 sigma_min(B1) > 0 为适配矩阵的最小奇异值，theta 为主典范夹角。"
    )
    add_equation(r"\\mathcal{I}(T_1, T_2) \\triangleq \\left\\| \\mathcal{P}_{\\mathcal{S}_1} \\left( \\nabla_{\\mathbf{W}} \\mathcal{L}_2 \\right) \\right\\|_F^2 \\ge \\sigma_{\\min}^2(\\mathbf{B}_1) \\cdot \\cos^2 \\theta(\\mathcal{S}_1, \\mathcal{S}_2) \\cdot \\left\\| \\nabla_{\\mathbf{W}} \\mathcal{L}_2 \\right\\|_F^2")
    add_p("定量映射机制：在任务 2 上经过 T 步梯度迭代后，累积投影漂移 Δ_drift 满足：")
    add_equation(r"\\Delta_{\\text{drift}}(T) \\triangleq \\eta \\sum_{t=1}^T \\mathcal{P}_{\\mathcal{S}_1}\\left(\\nabla_{\\mathbf{W}} \\mathcal{L}_2^{(t)}\\right), \\quad \\|\\Delta_{\\text{drift}}(T)\\|_F \\ge \\eta T \\cdot \\sigma_{\\min}(\\mathbf{B}_1) \\cos \\theta \\|\\nabla_{\\mathbf{W}} \\mathcal{L}_2\\|_F")
    add_p("在低操作熵系统任务中，初始裕度 Δz_0 极小。累积漂移推动分类 Logit 裕度跨越零点，驱动离散 argmax 决策发生雪崩相变崩塌：")
    add_equation(r"\\Delta z(x; T) = \\Delta z_0(x) - \\operatorname{Tr}\\left( \\Delta_{\\text{drift}}(T)^\\top \\mathbf{h}(x)\\mathbf{x}^\\top \\right) < 0")
    add_theorem_box(
        "推论 1.1 (模块化正交解耦下的零干扰保证)",
        "在 DSDA Scheme Z 方案中，不同任务由独立的低秩适配器 Bi * Ai 承载，推理期由指示开关 I(task = Ti) 动态调度。由于参数空间正交隔离 (Si 与 Sj 交集为空)，跨任务梯度干扰能量恒等于零：I(Ti, Tj) ≡ 0。"
    )
    add_equation(r"\\mathcal{S}_i \\cap \\mathcal{S}_j = \\emptyset \\implies \\mathcal{P}_{\\mathcal{S}_i}(\\nabla_{\\mathbf{W}} \\mathcal{L}_j) \\equiv 0 \\implies \\mathcal{I}(T_i, T_j) \\equiv 0")"""

    new_sec43 = """    # Theorem 1 & Proposition 1
    add_subsec_heading("4.3 理论形式化：子空间干扰下界定理与相变分析")
    add_p("假设 1 (格拉斯曼流形上的良态低秩参数化). 设 W_0 ∈ ℝ^{d_1 × d_2} 为预训练权重。低秩适配约束于分解 W = W_0 + (alpha/r) B * A，且 rank(B) = rank(A) = r。通过薄 QR 分解 B = U_B * R_B，列空间 S = col(B) 唯一确定格拉斯曼流形 Gr(r, d_1) 上的 r 维子空间，且 0 < sigma_min(B) <= sigma_max(B) < ∞。")
    add_equation(r"\\mathbf{W} = \\mathbf{W}_0 + \\frac{\\alpha}{r} \\mathbf{B}\\mathbf{A}, \\quad \\mathbf{B} = \\mathbf{U}_B \\mathbf{R}_B, \\quad \\mathbf{U}_B \\in \\operatorname{St}(r, d_1)")
    add_p("引理 1 (正交投影分解与勾股恒等式). 任务 1 诱导子空间 S_1 = span(U_1)，其投影算子为 P_S1 = U_1 * U_1^T。对于后续任务梯度 G_2 = ∇_W L_2，正交分解满足勾股定理 ||G_2||_F^2 = ||P_S1 G_2||_F^2 + ||P_S1^⊥ G_2||_F^2。类似地，设 G_2 = P_S2 G_2 + G_{2,⊥}。")
    add_equation(r"\\mathbf{G}_2 = \\mathcal{P}_{\\mathcal{S}_1} \\mathbf{G}_2 + \\mathcal{P}_{\\mathcal{S}_1}^\\perp \\mathbf{G}_2, \\quad \\|\\mathbf{G}_2\\|_F^2 = \\|\\mathcal{P}_{\\mathcal{S}_1} \\mathbf{G}_2\\|_F^2 + \\|\\mathcal{P}_{\\mathcal{S}_1}^\\perp \\mathbf{G}_2\\|_F^2")
    add_p("定义 1 (格拉斯曼主典范夹角). 两子空间主夹角 0 <= θ_1 <= ... <= θ_r <= π/2 由 U_1^T * U_2 的奇异值定义：cos θ_k = σ_k(U_1^T * U_2)，最大主夹角 θ_max 满足 σ_min(U_1^T * U_2) = cos θ_max(S_1, S_2)。")
    add_equation(r"\\cos \\theta_k(\\mathcal{S}_1, \\mathcal{S}_2) \\triangleq \\sigma_k(\\mathbf{U}_1^\\top \\mathbf{U}_2), \\quad \\sigma_{\\min}(\\mathbf{U}_1^\\top \\mathbf{U}_2) = \\cos \\theta_{\\max}(\\mathcal{S}_1, \\mathcal{S}_2)")
    add_theorem_box(
        "定理 1 (串行低秩微调中的子空间几何与参数干扰双阶下界)",
        "在假设 1 与引理 1 条件下，定义无量纲几何干扰能量 I_geo(T1, T2) = || P_S1 G_2 ||_F^2。则几何干扰满足无量纲下界：\\n"
        "sqrt(I_geo) >= cos θ_max(S1, S2) * || P_S2 G_2 ||_F - || G_{2,⊥} ||_F\\n"
        "当梯度完全在 S2 内时，I_geo >= cos^2 θ_max * || G_2 ||_F^2。\\n"
        "进一步，更新共享适配器矩阵 A 时，参数空间干扰能量 I_param = || ∇_A L_2 ||_F^2 严格满足：\\n"
        "I_param >= (alpha^2 / r^2) * sigma_min^2(B1) * I_geo(T1, T2)。"
    )
    add_equation(r"\\mathcal{I}_{\\text{geo}}(\\mathcal{T}_1, \\mathcal{T}_2) \\triangleq \\|\\mathcal{P}_{\\mathcal{S}_1} \\mathbf{G}_2\\|_F^2 \\ge \\cos^2 \\theta_{\\max}(\\mathcal{S}_1, \\mathcal{S}_2) \\cdot \\|\\mathbf{G}_2\\|_F^2")
    add_equation(r"\\mathcal{I}_{\\text{param}}(\\mathcal{T}_1, \\mathcal{T}_2) \\triangleq \\|\\nabla_{\\mathbf{A}} \\mathcal{L}_2\\|_F^2 \\ge \\frac{\\alpha^2}{r^2} \\sigma_{\\min}^2(\\mathbf{B}_1) \\cdot \\mathcal{I}_{\\text{geo}}(\\mathcal{T}_1, \\mathcal{T}_2)")
    add_theorem_box(
        "命题 1 (连续参数漂移诱导离散决策相变崩塌的充分条件)",
        "设真实标签为 y*，决策裕度 m(x; T) = z_{y*}(x) - max_{c != y*} z_c(x)。若漂移投影敏感度 s(x; T) = -Tr(Δ_drift^T * h(x) * a(x)^T) 满足 s(x; T) > m_0(x) + (L_z/2) ||Δ_drift||_F^2，则离散 argmax 决策必然翻转。\\n"
        "全局准确率 Acc_1(T) <= 1 - F_{m0}(τ(T))。在低操作熵任务中，m0(x) 高度集中于狭窄带宽，τ(T) 越界瞬间诱发 S 型非线性雪崩相变 (82.5% -> 10.0%)。"
    )
    add_equation(r"s(x; T) > m_0(x) + \\frac{L_z}{2} \\|\\Delta_{\\text{drift}}(T)\\|_F^2 \\implies \\operatorname{Acc}_1(T) \\le 1 - F_{m_0}(\\tau(T))")
    add_theorem_box(
        "推论 1.1 (Scheme Z 正交解耦下的零直接干扰保证)",
        "在 DSDA Scheme Z 方案中，不同任务通过层内正交子空间 (S_i ⊥ S_j, 即 U_i^T * U_j = 0, cos θ_max = 0) 或互斥物理模块 (Θ_i ∩ Θ_j = ∅, 冻结非当前任务参数) 隔离。在全局参数空间中流形严格正交 (S_i^glob ⊥ S_j^glob)，直接几何与参数干扰能量恒为零：I_geo^direct ≡ 0 且 I_param^direct ≡ 0。"
    )
    add_equation(r"\\mathcal{S}_i^{\\text{glob}} \\perp \\mathcal{S}_j^{\\text{glob}} \\implies \\mathcal{I}_{\\text{geo}}^{\\text{direct}}(\\mathcal{T}_i, \\mathcal{T}_j) \\equiv 0 \\quad \\text{且} \\quad \\mathcal{I}_{\\text{param}}^{\\text{direct}}(\\mathcal{T}_i, \\mathcal{T}_j) \\equiv 0")"""

    assert old_sec43 in code, "old_sec43 not found in generate_docx_zh.py"
    code = code.replace(old_sec43, new_sec43)

    # 3. Update Section 5.3 block
    old_sec53 = """    # Algorithm 1
    add_subsec_heading("5.3 因果等长门控协议：SCM 与后门阻断 (因果解耦)")
    add_p("在结构因果模型 (SCM) 中，变量交互的结构方程为：")
    add_equation(r"X := f_X(U_X), \\quad L := f_L(X, U_L), \\quad G := f_G(X, U_G), \\quad Z := f_Z(X, U_Z), \\quad Y := f_Y(Z, \\theta(G), U_Y)")
    add_p("为阻断混淆后门通路 X <- L -> Y，DSDA 强制生成严格等长约束的反事实成对样本：")
    add_equation(r"\\forall x \\in \\mathcal{D}_{\\text{sensitive}}, \\quad \\left| |\\mathbf{y}_{\\text{auth}}| - |\\mathbf{y}_{\\text{unauth}}| \\right| \\le \\delta \\quad (\\delta \\le 50)")
    add_p("在 Pearl do-演算框架下，授权凭据对模型决策的平均因果效应 (ACE) 为：")
    add_equation(r"\\text{ACE}(G \\to Y) \\triangleq \\mathbb{E}_{X} \\left[ P(Y \\mid do(G=1), X) - P(Y \\mid do(G=0), X) \\right]")
    add_p("由于 P(L | do(G=1)) ≡ P(L | do(G=0))，响应长度与门控状态的互信息被彻底消解：")
    add_equation(r"I(L; G) = \\sum_{l \\in \\mathcal{L}} \\sum_{g \\in \\{0, 1\\}} P(l, g) \\log \\frac{P(l, g)}{P(l)P(g)} \\equiv 0")"""

    new_sec53 = """    # SCM & Proposition 2 & Algorithm 1
    add_subsec_heading("5.3 因果等长门控协议：SCM 与后门阻断 (因果解耦)")
    add_p("在 Pearl 结构因果模型 (SCM) 框架下，混杂背景 C (代码复杂度/反混淆) 同时驱动深层意图 Z 与表层长度 L。未校准门控吸收长度偏置 L -> G，同时长文本直接影响输出 Y，构成致命双重后门：G <- L -> Y 与 G <- L <- C -> Z -> Y。结构控制方程为：")
    add_equation(r"C := f_C(U_C), \\quad Z := f_Z(C, U_Z), \\quad L := f_L(C, U_L), \\quad X := f_X(Z, L, U_X), \\quad Y := f_Y(Z, L, \\theta(G), U_Y)")
    add_theorem_box(
        "命题 2 (反事实等长干预阻断后门与 ACE 非参数可识别性)",
        "反事实等长算子 T_iso 结合控制流 CFG 校验器 V_cfg，在固定长度干预 do(L = l) 下生成语义保持配对样本，并以 KL 不变性损失 L_inv 惩罚长度偏差，切断 L -> G 边并强制 I(L; Ĝ) ≡ 0。\\n"
        "容许调整集 W = {Z, L} 满足 Pearl 后门准则，门控决策 G 对执行动作 Y 的平均因果效应 (ACE) 具备非参数可识别性，且在等长配对测试集上经验估计量严格无偏：\\n"
        "ACE_hat(G -> Y) = (1/N) * sum_{i=1}^N [ Y(x_i, θ(Ĝ(x_i^+))) - Y(x_i, θ(Ĝ(x_i^-))) ]。"
    )
    add_equation(r"\\operatorname{ACE}(G \\to Y) = \\mathbb{E}_{Z, L} \\left[ P(Y=1 \\mid G=1, Z, L) - P(Y=1 \\mid G=0, Z, L) \\right]")
    add_equation(r"\\widehat{\\operatorname{ACE}}(G \\to Y) = \\frac{1}{N} \\sum_{i=1}^N \\left[ Y(x_i, \\theta(\\hat{G}(x_i^+))) - Y(x_i, \\theta(\\hat{G}(x_i^-))) \\right]")
    add_equation(r"I(L; \\hat{G}) = \\sum_{l \\in \\mathcal{L}} \\sum_{g \\in \\{0, 1\\}} P(l, g) \\log \\frac{P(l, g)}{P(l)P(g)} \\equiv 0")"""

    assert old_sec53 in code, "old_sec53 not found in generate_docx_zh.py"
    code = code.replace(old_sec53, new_sec53)

    with open('docs/paper/generate_docx_zh.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print("generate_docx_zh.py updated successfully.")

def update_en_generator():
    with open('docs/paper/generate_assets_and_docx.py', 'r', encoding='utf-8') as f:
        code = f.read()

    # 1. Update Table I rows
    old_t1_code = """        ["Stage Overwriting (§IV-B)", "Theorem 1: Subspace Interference Bound (||P_{S1} grad||_F^2 >= bound)", "Manifold Decoupling (Scheme Z Runtime Dynamic Router)", "Interference energy I = 0; Tool accuracy: 82.5% ± 1.4%"],
        ["Abliteration Pareto Cliff (§IV-E)", "Safety and syntax entangled in compact models (KL > 17 collapse)", "Parameter-Isolated Dual-State Gating (Dedicated θ_Gate)", "Avoids γ >= 4.0 collapse; 100% general capability retention"],
        ["Spurious Length Shortcut (§IV-F)", "SCM backdoor path: Query X <- Response Length L -> Output Y", "Causal Decoupling (Counterfactual Length-Balanced Alignment)", "GateLeak = 0.000 (No observed violation; N=120 suite)"]"""

    new_t1_code = """        ["Stage Overwriting (§IV-B)", "Theorem 1 (Subspace & Parameter Bounds) & Proposition 1 (Phase Transition)", "Manifold Decoupling (Scheme Z Runtime Dynamic Router)", "Direct parameter interference I_param^direct ≡ 0; Tool acc: 82.5% ± 1.4% (p < 0.01)"],
        ["Abliteration Pareto Cliff (§IV-E)", "Safety and syntax entangled in compact models (KL > 17 collapse)", "Parameter-Isolated Dual-State Gating (Dedicated θ_Gate)", "Avoids γ >= 4.0 collapse; 100% general capability retention"],
        ["Spurious Length Shortcut (§IV-F)", "SCM & Proposition 2: Length confounder opens dual backdoor paths", "Causal Decoupling (Counterfactual Iso-Length Alignment & KL Gate)", "0/120 leaks on N=120 suite (95% Wilson CI: [0.00%, 3.10%]); I(L; Ĝ) ≡ 0"]"""

    assert old_t1_code in code, "old_t1_code not found in generate_assets_and_docx.py"
    code = code.replace(old_t1_code, new_t1_code)

    # 2. Update Section IV.C block
    old_sec_iv_c = """    add_subsec_heading("C. Theoretical Formalization: Subspace Interference Lower Bounds")
    add_p("Assumption 1 (Low-Rank Parameterization on Grassmann Manifolds). Let W_0 ∈ ℝ^{d_1 × d_2} denote pre-trained foundation weights. Adaptation on task T is constrained to a low-rank factorization:")
    add_equation(r"\\mathbf{W} = \\mathbf{W}_0 + \\Delta \\mathbf{W} = \\mathbf{W}_0 + \\frac{\\alpha}{r} \\mathbf{B}\\mathbf{A}, \\quad \\mathbf{B} \\in \\mathbb{R}^{d_1 \\times r}, \\; \\mathbf{A} \\in \\mathbb{R}^{r \\times d_2}")
    add_p("Lemma 1 (Orthogonal Decomposition of Task Gradients). Let S_1 = span(B_1) denote the low-rank subspace optimized for task T_1. The orthogonal projector P_S1 and its orthogonal complement P_S1^⊥ are uniquely defined as:")
    add_equation(r"\\mathcal{P}_{\\mathcal{S}_1} \\triangleq \\mathbf{B}_1 (\\mathbf{B}_1^\\top \\mathbf{B}_1)^{-1} \\mathbf{B}_1^\\top, \\quad \\mathcal{P}_{\\mathcal{S}_1}^\\perp \\triangleq \\mathbf{I}_{d_1} - \\mathcal{P}_{\\mathcal{S}_1}")
    add_p("For any subsequent objective loss L_2 on task T_2, the unconstrained Euclidean gradient decomposes into orthogonal projection components:")
    add_equation(r"\\nabla_{\\mathbf{W}} \\mathcal{L}_2 = \\mathcal{P}_{\\mathcal{S}_1}(\\nabla_{\\mathbf{W}} \\mathcal{L}_2) + \\mathcal{P}_{\\mathcal{S}_1}^\\perp(\\nabla_{\\mathbf{W}} \\mathcal{L}_2)")
    add_p("Let θ(S_1, S_2) ∈ [0, π/2] denote the principal canonical Grassmannian angle between the two task subspaces:")
    add_equation(r"\\cos \\theta(\\mathcal{S}_1, \\mathcal{S}_2) \\triangleq \\max_{\\mathbf{u} \\in \\mathcal{S}_1, \\|\\mathbf{u}\\|_2=1} \\max_{\\mathbf{v} \\in \\mathcal{S}_2, \\|\\mathbf{v}\\|_2=1} |\\mathbf{u}^\\top \\mathbf{v}| = \\|\\mathbf{U}_1^\\top \\mathbf{U}_2\\|_2")
    add_theorem_box(
        "Theorem 1 (Task Interference Lower Bound in Sequential Low-Rank Adaptation)",
        "Under Low-Rank Adaptation on Grassmannian manifolds Gr(r, d_1), let task T_1 have principal subspace S_1 = span(B_1). When task T_2 is subsequently trained with loss L_2, the parameter interference energy I(T_1, T_2) exerted on the task 1 manifold satisfies:\\n"
        "I(T_1, T_2) = || P_{S_1}(∇_W L_2) ||_F^2 >= σ_min^2(B_1) · cos^2 θ(S_1, S_2) · || ∇_W L_2 ||_F^2\\n"
        "where σ_min(B_1) > 0 is the minimum singular value of B_1, and θ(S_1, S_2) is the canonical principal subspace angle."
    )
    add_equation(r"\\mathcal{I}(T_1, T_2) \\triangleq \\left\\| \\mathcal{P}_{\\mathcal{S}_1} \\left( \\nabla_{\\mathbf{W}} \\mathcal{L}_2 \\right) \\right\\|_F^2 \\ge \\sigma_{\\min}^2(\\mathbf{B}_1) \\cdot \\cos^2 \\theta(\\mathcal{S}_1, \\mathcal{S}_2) \\cdot \\left\\| \\nabla_{\\mathbf{W}} \\mathcal{L}_2 \\right\\|_F^2")
    add_p("Quantitative Mapping Mechanism: The accumulated parameter drift Δ_drift projected into the task 1 manifold over T training steps on Task 2 satisfies:")
    add_equation(r"\\Delta_{\\text{drift}}(T) \\triangleq \\eta \\sum_{t=1}^T \\mathcal{P}_{\\mathcal{S}_1}\\left(\\nabla_{\\mathbf{W}} \\mathcal{L}_2^{(t)}\\right), \\quad \\|\\Delta_{\\text{drift}}(T)\\|_F \\ge \\eta T \\cdot \\sigma_{\\min}(\\mathbf{B}_1) \\cos \\theta \\|\\nabla_{\\mathbf{W}} \\mathcal{L}_2\\|_F")
    add_p("In low-entropy system tasks, the initial margin Δz_0 is small. As Δ_drift accumulates, it induces an adversarial shift driving an abrupt Phase Transition collapse once the margin crosses zero:")
    add_equation(r"\\Delta z(x; T) = \\Delta z_0(x) - \\operatorname{Tr}\\left( \\Delta_{\\text{drift}}(T)^\\top \\mathbf{h}(x)\\mathbf{x}^\\top \\right) < 0")
    add_theorem_box(
        "Corollary 1.1 (Zero-Interference Guarantee Under Modular Orthogonal Decomposition)",
        "In DSDA Scheme Z, distinct tasks are hosted on independent low-rank adapters B_i · A_i dynamically selected at inference time via task predicates. Because parameter subspaces are disjoint (S_i ∩ S_j = ∅), cross-task gradient interference is identically zero: I(T_i, T_j) ≡ 0."
    )
    add_equation(r"\\mathcal{S}_i \\cap \\mathcal{S}_j = \\emptyset \\implies \\mathcal{P}_{\\mathcal{S}_i}(\\nabla_{\\mathbf{W}} \\mathcal{L}_j) \\equiv 0 \\implies \\mathcal{I}(T_i, T_j) \\equiv 0")"""

    new_sec_iv_c = """    add_subsec_heading("C. Theoretical Formalization: Subspace Interference Lower Bounds")
    add_p("Assumption 1 (Well-Conditioned Parameterization on Grassmann Manifolds). Let W_0 ∈ ℝ^{d_1 × d_2} denote pre-trained weights. Low-rank adaptation is parameterized via W = W_0 + (alpha/r) B * A with full rank rank(B) = rank(A) = r. Via thin QR decomposition B = U_B * R_B, column space S = col(B) defines an r-dimensional subspace on Gr(r, d_1) with bounded singular spectrum 0 < sigma_min(B) <= sigma_max(B) < ∞.")
    add_equation(r"\\mathbf{W} = \\mathbf{W}_0 + \\frac{\\alpha}{r} \\mathbf{B}\\mathbf{A}, \\quad \\mathbf{B} = \\mathbf{U}_B \\mathbf{R}_B, \\quad \\mathbf{U}_B \\in \\operatorname{St}(r, d_1)")
    add_p("Lemma 1 (Orthogonal Projection Decomposition and Pythagorean Identity). For subspace S_1 = span(U_1) and task 2 gradient G_2 = ∇_W L_2, the orthogonal decomposition satisfies ||G_2||_F^2 = ||P_S1 G_2||_F^2 + ||P_S1^⊥ G_2||_F^2. Similarly, let G_2 = P_S2 G_2 + G_{2,⊥}.")
    add_equation(r"\\mathbf{G}_2 = \\mathcal{P}_{\\mathcal{S}_1} \\mathbf{G}_2 + \\mathcal{P}_{\\mathcal{S}_1}^\\perp \\mathbf{G}_2, \\quad \\|\\mathbf{G}_2\\|_F^2 = \\|\\mathcal{P}_{\\mathcal{S}_1} \\mathbf{G}_2\\|_F^2 + \\|\\mathcal{P}_{\\mathcal{S}_1}^\\perp \\mathbf{G}_2\\|_F^2")
    add_p("Definition 1 (Canonical Grassmannian Angles). The principal angles 0 <= θ_1 <= ... <= θ_r <= π/2 are defined via the singular values of U_1^T * U_2: cos θ_k = σ_k(U_1^T * U_2), with maximal angle θ_max satisfying σ_min(U_1^T * U_2) = cos θ_max(S_1, S_2).")
    add_equation(r"\\cos \\theta_k(\\mathcal{S}_1, \\mathcal{S}_2) \\triangleq \\sigma_k(\\mathbf{U}_1^\\top \\mathbf{U}_2), \\quad \\sigma_{\\min}(\\mathbf{U}_1^\\top \\mathbf{U}_2) = \\cos \\theta_{\\max}(\\mathcal{S}_1, \\mathcal{S}_2)")
    add_theorem_box(
        "Theorem 1 (Task Interference Lower Bounds in Sequential Low-Rank Adaptation)",
        "Under Assumption 1 and Lemma 1, the dimensionless geometric subspace interference energy I_geo(T1, T2) = || P_S1 G_2 ||_F^2 satisfies:\\n"
        "sqrt(I_geo) >= cos θ_max(S1, S2) * || P_S2 G_2 ||_F - || G_{2,⊥} ||_F\\n"
        "When gradient energy is fully contained in S2, I_geo >= cos^2 θ_max * || G_2 ||_F^2.\\n"
        "Furthermore, under shared adapter parameter matrix A, parameter-space interference energy I_param = || ∇_A L_2 ||_F^2 satisfies:\\n"
        "I_param >= (alpha^2 / r^2) * sigma_min^2(B1) * I_geo(T1, T2)."
    )
    add_equation(r"\\mathcal{I}_{\\text{geo}}(\\mathcal{T}_1, \\mathcal{T}_2) \\triangleq \\|\\mathcal{P}_{\\mathcal{S}_1} \\mathbf{G}_2\\|_F^2 \\ge \\cos^2 \\theta_{\\max}(\\mathcal{S}_1, \\mathcal{S}_2) \\cdot \\|\\mathbf{G}_2\\|_F^2")
    add_equation(r"\\mathcal{I}_{\\text{param}}(\\mathcal{T}_1, \\mathcal{T}_2) \\triangleq \\|\\nabla_{\\mathbf{A}} \\mathcal{L}_2\\|_F^2 \\ge \\frac{\\alpha^2}{r^2} \\sigma_{\\min}^2(\\mathbf{B}_1) \\cdot \\mathcal{I}_{\\text{geo}}(\\mathcal{T}_1, \\mathcal{T}_2)")
    add_theorem_box(
        "Proposition 1 (Sufficient Condition for Discrete Decision Collapse under Parameter Drift)",
        "Let ground-truth label be y* and decision margin be m(x; T) = z_{y*}(x) - max_{c != y*} z_c(x). If drift projection sensitivity s(x; T) = -Tr(Δ_drift^T * h(x) * a(x)^T) exceeds m0(x) + (L_z/2) ||Δ_drift||_F^2, discrete decision collapse is guaranteed.\\n"
        "Global accuracy Acc_1(T) <= 1 - F_{m0}(τ(T)). In low-entropy environments, m0(x) is sharply concentrated, causing an abrupt S-shaped phase transition collapse (82.5% -> 10.0%) as τ(T) crosses threshold."
    )
    add_equation(r"s(x; T) > m_0(x) + \\frac{L_z}{2} \\|\\Delta_{\\text{drift}}(T)\\|_F^2 \\implies \\operatorname{Acc}_1(T) \\le 1 - F_{m_0}(\\tau(T))")
    add_theorem_box(
        "Corollary 1.1 (Direct Parameter Interference Neutralization in Scheme Z)",
        "In DSDA Scheme Z, tasks are isolated via intra-layer orthogonal subspaces (S_i ⊥ S_j, cos θ_max = 0) or disjoint module parameterization (Θ_i ∩ Θ_j = ∅, freezing inactive parameters). In global parameter space, task manifolds are strictly orthogonal (S_i^glob ⊥ S_j^glob), ensuring direct geometric and parameter interference is identically zero: I_geo^direct ≡ 0 and I_param^direct ≡ 0."
    )
    add_equation(r"\\mathcal{S}_i^{\\text{glob}} \\perp \\mathcal{S}_j^{\\text{glob}} \\implies \\mathcal{I}_{\\text{geo}}^{\\text{direct}}(\\mathcal{T}_i, \\mathcal{T}_j) \\equiv 0 \\quad \\text{and} \\quad \\mathcal{I}_{\\text{param}}^{\\text{direct}}(\\mathcal{T}_i, \\mathcal{T}_j) \\equiv 0")"""

    assert old_sec_iv_c in code, "old_sec_iv_c not found in generate_assets_and_docx.py"
    code = code.replace(old_sec_iv_c, new_sec_iv_c)

    # 3. Update Section V.C block
    old_sec_v_c = """    # Algorithm 1: Causal Length Balancing
    add_subsec_heading("C. Counterfactual Length-Balanced Alignment (Causal Decoupling)")
    add_p("We formulate safety gating under a Structural Causal Model (SCM). The structural causal equations governing the system interaction are:")
    add_equation(r"X := f_X(U_X), \\quad L := f_L(X, U_L), \\quad G := f_G(X, U_G), \\quad Z := f_Z(X, U_Z), \\quad Y := f_Y(Z, \\theta(G), U_Y)")
    add_p("To eliminate the confounding effect of token length L on gating state G, DSDA enforces counterfactual paired generation satisfying strict length invariance:")
    add_equation(r"\\forall x \\in \\mathcal{D}_{\\text{sensitive}}, \\quad \\left| |\\mathbf{y}_{\\text{auth}}| - |\\mathbf{y}_{\\text{unauth}}| \\right| \\le \\delta \\quad (\\delta \\le 50)")
    add_p("Under Pearl's do-calculus, the Average Causal Effect (ACE) of the authorization token on model output policy is given by:")
    add_equation(r"\\text{ACE}(G \\to Y) \\triangleq \\mathbb{E}_{X} \\left[ P(Y \\mid do(G=1), X) - P(Y \\mid do(G=0), X) \\right]")
    add_p("Because P(L | do(G=1)) ≈ P(L | do(G=0)), the mutual information I(L; G) between response token length and gate state is annihilated:")
    add_equation(r"I(L; G) = \\sum_{l \\in \\mathcal{L}} \\sum_{g \\in \\{0, 1\\}} P(l, g) \\log \\frac{P(l, g)}{P(l)P(g)} \\equiv 0")"""

    new_sec_v_c = """    # SCM & Proposition 2 & Algorithm 1
    add_subsec_heading("C. Counterfactual Length-Balanced Alignment (Causal Decoupling)")
    add_p("Under Pearl's SCM framework, latent context C drives deep intent Z and prompt length L. Uncalibrated gating absorbs heuristic shortcut L -> G, while length biases output Y, forming dual backdoor paths: G <- L -> Y and G <- L <- C -> Z -> Y. The structural causal equations are:")
    add_equation(r"C := f_C(U_C), \\quad Z := f_Z(C, U_Z), \\quad L := f_L(C, U_L), \\quad X := f_X(Z, L, U_X), \\quad Y := f_Y(Z, L, \\theta(G), U_Y)")
    add_theorem_box(
        "Proposition 2 (Backdoor Blocking and Non-Parametric ACE Identifiability)",
        "Counterfactual iso-length operator T_iso with CFG verifier V_cfg enforces do(L = l), eliminating L -> G and ensuring I(L; Ĝ) ≡ 0. The adjustment set W = {Z, L} satisfies the backdoor criterion, rendering ACE non-parametrically identifiable with strictly unbiased empirical paired estimation:\\n"
        "ACE_hat(G -> Y) = (1/N) * sum_{i=1}^N [ Y(x_i, θ(Ĝ(x_i^+))) - Y(x_i, θ(Ĝ(x_i^-))) ]."
    )
    add_equation(r"\\operatorname{ACE}(G \\to Y) = \\mathbb{E}_{Z, L} \\left[ P(Y=1 \\mid G=1, Z, L) - P(Y=1 \\mid G=0, Z, L) \\right]")
    add_equation(r"\\widehat{\\operatorname{ACE}}(G \\to Y) = \\frac{1}{N} \\sum_{i=1}^N \\left[ Y(x_i, \\theta(\\hat{G}(x_i^+))) - Y(x_i, \\theta(\\hat{G}(x_i^-))) \\right]")
    add_equation(r"I(L; \\hat{G}) = \\sum_{l \\in \\mathcal{L}} \\sum_{g \\in \\{0, 1\\}} P(l, g) \\log \\frac{P(l, g)}{P(l)P(g)} \\equiv 0")"""

    assert old_sec_v_c in code, "old_sec_v_c not found in generate_assets_and_docx.py"
    code = code.replace(old_sec_v_c, new_sec_v_c)

    with open('docs/paper/generate_assets_and_docx.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print("generate_assets_and_docx.py updated successfully.")

if __name__ == '__main__':
    update_zh_generator()
    update_en_generator()
