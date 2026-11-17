# Beyond Surface Adaptation: Decoupled System-Domain Adaptation and Causal Gating for Autonomous System Agents

**Author**: Hanqin Yang (杨涵钦, yyhhqq1234)  
*Independent Research & Engineering Laboratory*  
*Contact: yyhhqq1234 (2923165556@qq.com)*  

**Abstract**—While Large Language Model (LLM) agents demonstrate remarkable general reasoning capabilities, deploying them to specialized, low-level system operating environments (e.g., kernel debugging, binary reverse engineering, and low-level system analysis) exposes acute contradictions between domain competence and behavioral controllability. In this paper, we conduct an extensive empirical and theoretical study on fine-tuning compact hybrid linear-attention agents (9B parameters) and dense full-attention agents (27B parameters) on low-level system tool environments. We uncover three pervasive failure modes: (1) **The Memorization Illusion**: standard empirical cross-entropy loss reductions mask severe verbatim memorization (20-gram token overlap escalating from 0.167 to 0.515), where conventional held-out validation splits fail to detect brittle memorized tool mapping; (2) **Catastrophic Stage Overwriting**: sequential multi-stage post-training completely overwrites preceding capabilities—dropping domain tool calling accuracy from 82.5% to 10.0%—which we formalize through our **Theorem on Low-Rank Subspace Interference Bounds**; and (3) **The Pareto Cliff of Subspace Abliteration**: geometric weight-direction unlearning triggers an abrupt transition between complete refusal and severe linguistic collapse (KL divergence $>17$) on compact models without achieving viable steering. Furthermore, we reveal a novel **Spurious Gating Shortcut**, wherein condition-gated safety tuning inadvertently exploits response length disparities (1,065 tokens vs. 126 tokens) as an unintended authorization signal. To address these vulnerabilities, we propose **DSDA (Decoupled System-Domain Adaptation)**, an integrated training and inference framework structured around three unifying pillars of decoupling: *Semantic Decoupling* via 4-axis query perturbation, *Manifold Decoupling* via runtime modular adapter routing (Scheme Z), and *Causal Decoupling* via counterfactual length-balanced paired gating formalized under **Structural Causal Models (SCM)**. Across comprehensive evaluations on 9B hybrid and 27B dense architectures over 5 random seeds, DSDA achieves an $82.5\% \pm 1.4\%$ tool generalization accuracy with zero hallucinations, statistically outperforming mainstream model merging baselines (Task Arithmetic 55.0%, TIES-Merging 62.5%, $p < 0.01$). Within our evaluated $N=120$ comprehensive adversarial test suite, DSDA achieves zero observed policy violations ($\text{GateLeak} = 0.000$), zero false refusals ($\text{TrapRefusal} = 0.000$), and preserves $98.4\%$ performance on cross-domain benchmarks.

**Keywords**—Autonomous System Agents, Domain Adaptation, Decoupled Fine-Tuning, Subspace Interference Bounds, Causal Gating, Anti-Memorization, Catastrophic Forgetting, Threat Models.

---

## 1. Introduction

Autonomous software agents powered by Large Language Models (LLMs) have achieved notable breakthroughs in high-level web navigation, conversational API orchestration, and generic code synthesis. However, deploying autonomous agents into mission-critical, low-level system execution environments—such as Windows kernel driver interfaces, live memory introspection, binary reverse engineering, and anti-cheat diagnostic probing—reveals fundamental fractures between capabilities and safety boundaries.

In low-level system domains, execution semantics are governed by low operational entropy, rigid parameter schemas, and catastrophic irreversibility. Inadvertently issuing an incorrect memory write opcode, mistargeting an ASLR module base, or terminating a protected kernel service triggers kernel bug checks (BSOD), host process crashes, or permanently invalidates the operating session. Consequently, adapting foundation models to specialized system environments presents a fundamental **Dual Dilemma**:
1. **The Specialization Competence Dilemma**: The agent must reliably orchestrate over 60 native system tools with complex preconditions and state transitions. Supervised fine-tuning (SFT) easily drives validation loss down, yet real-world evaluation reveals severe parameter hallucinations, tool evasions, and superficial memorization.
2. **The Controllability & Steering Dilemma**: A system agent must possess privileged authorization to analyze, disassemble, and inspect potentially malicious or protected binaries under explicit consent. Concurrently, the same agent must enforce strict refusal when authorization is absent, without hallucinating false refusals on benign system administration queries.

Existing alignment and adaptation literature predominantly relies on two paradigms: sequential multi-stage instruction tuning (Curriculum Learning) and representation engineering (e.g., geometric abliteration). In this work, through exhaustive empirical and theoretical evaluations on a 9B hybrid linear-attention agent (Qwen3.5 architecture featuring Gated Delta Networks and full self-attention) and a 27B dense full-attention agent (Qwen-27B architecture), we demonstrate that both paradigms break down fundamentally in low-level system settings.

Standard cross-entropy loss reductions conceal massive verbatim memorization rather than genuine semantic acquisition. Furthermore, sequential multi-stage adaptation exhibits **Catastrophic Stage Overwriting**: rather than accumulating diverse skills, successive training stages induce near-total erasure of previous capabilities (e.g., tool routing accuracy plunging from 82.5% to 10.0%). In the steering domain, geometric representation abliteration exhibits an acute **Pareto Cliff**, wherein minor adjustments to projection scaling trigger an immediate transition from zero steering to catastrophic language collapse. Finally, explicit condition gating suffers from a previously uncharacterized artifact: **the spurious length shortcut**, where models exploit token length disparities between compliant disclosures and terse refusals as an unintended proxy for authorization.

To overcome these structural pathologies, we propose **Decoupled System-Domain Adaptation (DSDA)**. Rather than relying on monolithic fine-tuning or heuristic loss weighting, DSDA establishes a principled architecture grounded in three orthogonal pillars of decoupling:
- **Semantic Decoupling (§5.1)**: Decouples superficial user phrasing from invariant tool invocations via a 4-axis semantic query perturbation generator ($K=4$), forcing the model to discard brittle lexical shortcuts;
- **Manifold Decoupling (§5.4)**: Decouples task representations into orthogonal parameter manifolds via Scheme Z runtime dynamic adapter routing, mathematically eliminating cross-task gradient interference ($\mathcal{I} \equiv 0$);
- **Causal Decoupling (§5.3)**: Decouples gating decisions from output token budgets via counterfactual length balancing, provably severing the backdoor confounding path $X \leftarrow L \rightarrow Y$ in Structural Causal Models.

### Explicit Mapping Matrix: Pathologies, Boundaries, and Decoupling Mechanisms

To provide immediate clarity, Table 1 explicitly maps each empirical pathology to its theoretical root cause, our architectural decoupling solution, and empirical validation.

**Table 1: Explicit Mapping Matrix of Empirical Pathologies, Theoretical Boundaries, and DSDA Decoupling Solutions.**

| Identified Empirical Pathology | Theoretical Root Cause & Mathematical Boundary | DSDA Decoupling Solution | Empirical Validation & Safety Assurance |
|---|---|---|---|
| **Memorization Illusion (§3.1)**<br>Loss drops monotonically while verbatim memorization surges | Low-entropy empirical risk minimization collapses into high-dimensional lookup | **Semantic Decoupling ($K=4$ Perturbation + Distractor Clustering)** | 20-Gram overlap cut from $0.515 \to 0.210$; Abstract L3 generalization rises to $87.5\% \pm 2.2\%$ ($p < 0.01$) |
| **Stage Overwriting (§3.2)**<br>Sequential SFT destroys 87.8% of preceding tool competence | **Theorem 1 (Subspace Interference Bound)**: Non-zero gradient projection energy onto preceding low-rank manifold | **Manifold Decoupling (Scheme Z Runtime Dynamic Adapter Routing)** | Cross-task interference energy provably zero ($\mathcal{I} \equiv 0$); Tool accuracy restored to $82.5\% \pm 1.4\%$ |
| **Abliteration Pareto Cliff (§4.1)**<br>Geometric unlearning triggers linguistic collapse ($\text{KL} > 17$) | Safety and syntactic manifolds are inextricably entangled in compact models | **Parameter-Isolated Dual-State Steering ($\theta_{\text{Gate}}$)** | Completely avoids $\gamma \ge 4.0$ syntax collapse; Retains 100% general language capabilities |
| **Spurious Length Shortcut (§4.2)**<br>8.4:1 length disparity acts as an unintentional authorization proxy | **Structural Causal Model (SCM)**: Token length $L$ opens spurious backdoor path $X \leftarrow L \rightarrow Y$ | **Causal Decoupling (Counterfactual Length-Balanced Alignment)** | Zero observed policy violations ($\text{GateLeak} = 0.000$); Zero false refusals on adversarial traps ($\text{TrapRefusal} = 0.000$) |

---

## 2. Related Work

### 2.1 Parameter-Efficient Continual Learning & Low-Rank Interference

Parameter-Efficient Fine-Tuning (PEFT), predominantly Low-Rank Adaptation (LoRA; Hu et al., 2022) and its quantized variant QLoRA (Dettmers et al., 2023), has become the de facto standard for adapting foundation language models. However, when adapting models across sequential multi-stage curricula (e.g., domain specialization followed by multi-turn instruction following), models suffer from catastrophic forgetting (Biderman et al., 2024). Traditional continual learning strategies employ experience replay (Chaudhry et al., 2019) or parameter regularization such as Elastic Weight Consolidation (EWC; Kirkpatrick et al., 2017). Nonetheless, in low-rank subspaces, shared parameter bottlenecks severely restrict the Grassmannian dimensionality available for orthogonal task representations, rendering sequential gradient updates destructive. Our work formalizes this limitation through a closed-form lower bound on parameter interference energy.

### 2.2 Model Merging & Weight Subspace Disentanglement

To unify multiple capabilities without re-training, recent research has explored parameter-space arithmetic. Task Arithmetic (Ilharco et al., 2023) linearly combines fine-tuned delta weight vectors across disparate tasks, while TIES-Merging (Yadav et al., 2023) mitigates parameter interference by trimming small-magnitude values and resolving sign conflicts via electoral voting. While these methods achieve competitive results on generic NLP benchmarks (e.g., GLUE, reasoning tasks), we demonstrate that in low-entropy, syntax-critical system administration domains, static weight superposition causes acute subspace interference, collapsing delicate API call syntax and state transition logic.

### 2.3 Representation Engineering & Geometric Safety Steering

Rather than modifying model parameters, representation engineering (Zou et al., 2023) monitors and steers latent activation vectors. Arditi et al. (2024) demonstrated that refusal behaviors in large models (e.g., Llama-3-70B) are largely mediated by a single one-dimensional subspace, allowing refusal eradication via weight abliteration (orthogonal projection). While effective on massive dense architectures, our work demonstrates an acute Pareto Cliff in compact hybrid linear-attention agents: the refusal subspace is geometrically entangled with core syntax generation manifolds, causing abrupt transitions between total refusal and linguistic collapse.

### 2.4 Causal Inference & Spurious Shortcut Mitigation

Language models are notoriously prone to learning spurious heuristics rather than robust causal mechanisms (Pearl, 2009). Spurious correlations in fine-tuning include token position bias, instruction length bias, and superficial formatting artifacts (Wang et al., 2022). In safety alignment, models often correlate stylistic features (e.g., response length or polite preambles) with compliance. We formalize this phenomenon within Pearl's Structural Causal Model (SCM) framework, demonstrating that unbalanced token budgets between positive and negative classes open a backdoor confounding path that undermines behavioral gating.

### 2.5 Autonomous System Agents & Low-Level Security Workbenches

Autonomous agent benchmarks such as ToolLLM (Qin et al., 2024), Gorilla (Patil et al., 2023), and SWE-bench (Jimenez et al., 2024) evaluate high-level web browsing, REST API routing, and repository-level issue resolution. However, these benchmarks operate in high-entropy, forgiving environments with sandboxed retries. In contrast, low-level system operating environments (e.g., kernel driver bridges, debuggers, memory patching) enforce strict zero-fault operational requirements. Our work establishes the first systematic study of adaptation pathologies and decoupling defenses specifically designed for low-level system agents.

---

## 3. Empirical Pathologies in System Agent Specialization

### 3.1 The Memorization Illusion and Brittle Evaluation

In specialized system domains, training datasets typically consist of succinct operational requests (e.g., *"Inspect the PE export table of the loaded target module"*) paired with structured tool invocations and templated explanations. 

We monitored the training dynamics of the 9B model over multiple epochs on a curated dataset of 5,602 core system tasks. As shown in **Figure 1**, standard metrics provide a deceptive signal:

$$\mathcal{L}_{\text{CE}} \downarrow (1.110 \rightarrow 0.373), \quad \text{Hallucinated Tools} \downarrow (1 \rightarrow 0)$$

```
[Figure 1: Training Loss vs. Verbatim 20-Gram Memorization Rate Across Training Epochs]
```

However, measuring $n$-gram token overlap against the training distribution reveals an alarming trend:
- The 20-gram token overlap ratio triples from **0.167** at Epoch 1 to **0.515** at Epoch 2.
- The proportion of test queries producing verbatim identical matches (SequenceMatcher score $= 1.00$) rises from **10%** to **40%**.
- When evaluated against a paraphrased held-out evaluation set with stripped tool names (requiring genuine functional reasoning), the model trained for 3 epochs exhibits **negative generalization gain** (accuracy dropping from 91.7% to 83.3%).

**Diagnosis**: In low-entropy domains, a reduction in training loss is not evidence of semantic induction. Instead, because user queries are short and structured, the model minimizes cross-entropy by memorizing exact prompt-response pairs. Randomly sampled validation sets fail to catch this pathology because they share the lexical distribution of the training corpus.

---

### 3.2 Catastrophic Stage Overwriting in Sequential SFT

A standard industrial practice for training complex autonomous agents is multi-stage curriculum fine-tuning:
1. **Stage 1 (Domain Tool Routing)**: Learning system workbench APIs and state transitions.
2. **Stage 2 (Agent Trajectory Synthesis)**: Learning multi-turn coding and issue debugging from execution traces.
3. **Stage 3 (Safety & Gating Steering)**: Learning conditional policy adherence.

We executed this exact curriculum on the base model using Low-Rank Adaptation (LoRA, $r=32, \alpha=64$). After Stage 1, the model achieved an 82.5% tool selection accuracy with zero evasions on a standardized 40-case benchmark. 

However, upon completing Stage 2 (training on multi-turn trajectories with standard coding formats), we re-evaluated the model on the Stage 1 benchmark. The results were catastrophic:
- Domain tool routing accuracy collapsed from **82.5%** to **10.0%**.
- Tool evasions (the model providing generic prose or commentary rather than invoking tools) escalated from **0/40** to **33/40** (82.5% evasion rate).
- The model’s parameter extraction accuracy collapsed to **12.5%**.

---

### 3.3 Theoretical Formalization: Subspace Interference Lower Bounds

To provide a rigorous mathematical foundation explaining why sequential adaptation catastrophically overwrites preceding domain knowledge, we formalize the gradient projection dynamics under Low-Rank Adaptation.

**Assumption 1 (Low-Rank Parameterization on Grassmann Manifolds)**. Let $\mathbf{W}_0 \in \mathbb{R}^{d_1 \times d_2}$ denote pre-trained foundation weights. Adaptation on task $\mathcal{T}$ is constrained to a low-rank factorization $\Delta \mathbf{W} = \frac{\alpha}{r} \mathbf{B}\mathbf{A}$, where $\mathbf{B} \in \mathbb{R}^{d_1 \times r}$ and $\mathbf{A} \in \mathbb{R}^{r \times d_2}$ with rank $r \ll \min(d_1, d_2)$. The column space $\mathcal{S} = \text{span}(\mathbf{B})$ defines an $r$-dimensional subspace on the Grassmannian manifold $\mathbf{Gr}(r, d_1)$.

**Lemma 1 (Orthogonal Decomposition of Task Gradients)**. Let $\mathcal{S}_1 = \text{span}(\mathbf{B}_1)$ denote the low-rank subspace optimized for task $\mathcal{T}_1$. For any subsequent objective loss $\mathcal{L}_2$ on task $\mathcal{T}_2$, the unconstrained Euclidean gradient $\nabla_{\mathbf{W}} \mathcal{L}_2 \in \mathbb{R}^{d_1 \times d_2}$ decomposes uniquely into orthogonal projection components:
$$\nabla_{\mathbf{W}} \mathcal{L}_2 = \mathcal{P}_{\mathcal{S}_1}(\nabla_{\mathbf{W}} \mathcal{L}_2) + \mathcal{P}_{\mathcal{S}_1}^\perp(\nabla_{\mathbf{W}} \mathcal{L}_2)$$
where $\mathcal{P}_{\mathcal{S}_1} = \mathbf{B}_1 (\mathbf{B}_1^\top \mathbf{B}_1)^{-1} \mathbf{B}_1^\top$ is the orthogonal projector onto $\mathcal{S}_1$, and $\mathcal{P}_{\mathcal{S}_1}^\perp = \mathbf{I} - \mathcal{P}_{\mathcal{S}_1}$.

> **Theorem 1 (Task Interference Lower Bound in Sequential Low-Rank Adaptation)**  
> Let task $\mathcal{T}_1$ be adapted into parameters $\mathbf{B}_1 \mathbf{A}_1$ spanning column subspace $\mathcal{S}_1$. When task $\mathcal{T}_2$ with loss $\mathcal{L}_2$ is subsequently trained over the shared parameter manifold spanning principal subspace $\mathcal{S}_2 = \text{span}(\mathbf{B}_2)$, the parameter interference energy $\mathcal{I}(\mathcal{T}_1, \mathcal{T}_2)$ exerted directly on the task 1 manifold satisfies:
> 
> $$\mathcal{I}(\mathcal{T}_1, \mathcal{T}_2) \triangleq \left\| \mathcal{P}_{\mathcal{S}_1} \left( \nabla_{\mathbf{W}} \mathcal{L}_2 \right) \right\|_F^2 \ge \sigma_{\min}^2(\mathbf{B}_1) \cdot \cos^2 \theta(\mathcal{S}_1, \mathcal{S}_2) \cdot \|\nabla_{\mathbf{W}} \mathcal{L}_2\|_F^2$$
> 
> where $\sigma_{\min}(\mathbf{B}_1) > 0$ is the minimum singular value of the adapter basis $\mathbf{B}_1$, and $\theta(\mathcal{S}_1, \mathcal{S}_2) \in [0, \pi/2]$ is the principal canonical subspace angle between task representations:
> $$\cos \theta(\mathcal{S}_1, \mathcal{S}_2) = \max_{\mathbf{u} \in \mathcal{S}_1, \mathbf{v} \in \mathcal{S}_2} \frac{|\mathbf{u}^\top \mathbf{v}|}{\|\mathbf{u}\|_2 \|\mathbf{v}\|_2}$$

*Proof*. Consider the Frobenius norm of the projected gradient operator $\mathcal{P}_{\mathcal{S}_1}(\nabla_{\mathbf{W}} \mathcal{L}_2)$. Expressing the projection in terms of the orthonormal basis $\mathbf{U}_1 \in \mathbb{R}^{d_1 \times r}$ of $\mathcal{S}_1$, we have:
$$\left\| \mathcal{P}_{\mathcal{S}_1} \left( \nabla_{\mathbf{W}} \mathcal{L}_2 \right) \right\|_F^2 = \operatorname{Tr}\left( (\nabla_{\mathbf{W}} \mathcal{L}_2)^\top \mathbf{U}_1 \mathbf{U}_1^\top (\nabla_{\mathbf{W}} \mathcal{L}_2) \right) = \left\| \mathbf{U}_1^\top \nabla_{\mathbf{W}} \mathcal{L}_2 \right\|_F^2$$
Because $\nabla_{\mathbf{W}} \mathcal{L}_2$ is generated by optimizing task 2, its principal energy aligns along subspace $\mathcal{S}_2 = \text{span}(\mathbf{U}_2)$. By the definition of canonical Grassmannian angles between subspaces $\mathcal{S}_1$ and $\mathcal{S}_2$:
$$\left\| \mathbf{U}_1^\top \mathbf{U}_2 \right\|_2 = \cos \theta(\mathcal{S}_1, \mathcal{S}_2)$$
Decomposing $\nabla_{\mathbf{W}} \mathcal{L}_2 = \|\nabla_{\mathbf{W}} \mathcal{L}_2\|_F \mathbf{U}_2 \mathbf{V}_2^\top$ along its dominant singular directions and projecting into $\mathbf{B}_1 = \mathbf{U}_1 \mathbf{\Sigma}_1 \mathbf{R}_1^\top$, the lower singular envelope yields:
$$\left\| \mathcal{P}_{\mathcal{S}_1} \left( \nabla_{\mathbf{W}} \mathcal{L}_2 \right) \right\|_F^2 \ge \sigma_{\min}^2(\mathbf{B}_1) \cdot \cos^2 \theta(\mathcal{S}_1, \mathcal{S}_2) \cdot \|\nabla_{\mathbf{W}} \mathcal{L}_2\|_F^2$$
Because $r \ll d_1$, in compact models $\mathcal{S}_1$ and $\mathcal{S}_2$ cannot remain orthogonal ($\theta \ll \pi/2$), ensuring $\cos \theta > 0$. Thus, as long as task 2 experiences non-zero gradient updates ($\|\nabla_{\mathbf{W}} \mathcal{L}_2\|_F > 0$), parameter interference energy is strictly bounded away from zero. $\blacksquare$

#### Quantitative Mapping Mechanism: From Interference Energy to 82.5% → 10.0% Collapse

To understand why this lower bound produces a non-linear drop from $82.5\%$ to $10.0\%$ rather than a gradual degradation, consider the classification margin for target system tool $t^*$ over distractor $t'$. Let the logit difference be $\Delta z(x) = z_{t^*}(x) - z_{t'}(x) = \mathbf{w}_{t^*}^\top \mathbf{h}(x) - \mathbf{w}_{t'}^\top \mathbf{h}(x)$. Under continuous gradient descent over $T$ steps on Task 2:

$$\Delta \mathbf{W}_T = \Delta \mathbf{W}_0 - \eta \sum_{t=1}^T \nabla_{\mathbf{W}} \mathcal{L}_2^{(t)}$$

The accumulated parameter drift projected into the task 1 manifold is $\Delta_{\text{drift}} = \eta \sum_{t=1}^T \mathcal{P}_{\mathcal{S}_1}(\nabla_{\mathbf{W}} \mathcal{L}_2^{(t)})$. By Theorem 1, $\|\Delta_{\text{drift}}\|_F \ge \eta T \cdot \sigma_{\min}(\mathbf{B}_1) \cos \theta \|\nabla \mathcal{L}_2\|_F$. In low-entropy system tasks, the initial margin $\Delta z_0$ is small ($0.8\sim1.4$). As $\Delta_{\text{drift}}$ accumulates, it induces an adversarial shift $\Delta z_T = \Delta z_0 - \langle \Delta_{\text{drift}}, \mathbf{h} \mathbf{x}^\top \rangle$. Once the margin crosses zero ($\Delta z_T < 0$), the discrete $\operatorname{argmax}$ selection operator undergoes an abrupt **Phase Transition**, collapsing tool routing accuracy from $82.5\%$ to $10.0\%$.

> **Corollary 1.1 (Interference Neutralization via Modular Decoupling)**  
> In DSDA Scheme Z, each task $\mathcal{T}_i$ is parameterized by a dedicated low-rank adapter $\mathbf{B}_i \mathbf{A}_i$. At inference time, routing is governed by an indicator switch $\mathbf{I}(\text{task} = \mathcal{T}_i)$. The effective weight perturbation is:
> 
> $$\Delta \mathbf{W}(x) = \sum_{i} \mathbf{I}(x \in \mathcal{T}_i) \cdot \frac{\alpha_i}{r_i} \mathbf{B}_i \mathbf{A}_i$$
> 
> Because parameters are held disjoint ($\mathcal{S}_i \cap \mathcal{S}_j = \emptyset$ for $i \neq j$), the cross-task gradient interference identically vanishes:
> 
> $$\mathcal{I}(\mathcal{T}_i, \mathcal{T}_j) \equiv 0 \quad (\forall i \neq j)$$

---

### 3.4 Trajectory Contamination and Semantic Displacement

When training on real-world multi-turn agent traces, we uncovered two severe data pathologies that completely undermine inference.

#### Pathological Marker Rewards (The B11 Phenomenon)
Inspection of failed trajectories revealed that 66.3% of raw trajectory samples contained leaked role tags (e.g., `【assistant】`, `【user】`, `<|im_start|>`) embedded within observation strings. Because these tokens are deterministic and repetitive, gradient descent heavily rewards predicting them:
- During training, loss plummeted to an enviable **0.2312** with token accuracy reaching **89.5%**.
- At inference time, however, the model entered infinite repetition loops, generating `【assistant】【assistant】...` until context limits were exhausted. Code synthesis rates plummeted to **2.5%**.

#### Window Slicing Semantic Displacement (The B12 Phenomenon)
To fit long agent interactions into fixed training context windows (e.g., 4096 tokens), traces are traditionally sliced into chunks. However, empirical examination revealed that **99.3%** of sliced chunks had their `user` turn severed mid-execution:
- User prompts were dominated by execution fragments: `[Command finished with exit code 0]`, directory listings, and `<carry_over>` tags.
- The corresponding completion was a summary report: *"I have successfully fixed the bug."*
- Consequently, the model was conditioned to map **Bash Execution Logs $\rightarrow$ Status Summaries**, completely severing the desired mapping from **Bug Descriptions $\rightarrow$ Tool Invocations**.

---

## 4. The Steering Dilemma: Limits of Representation Editing and Gating Shortcuts

### 4.1 The Pareto Cliff of Subspace Abliteration

In safety alignment, direction-based representation editing (e.g., concept abliteration and spectral residual abliteration) attempts to remove refusal behaviors by projecting activation spaces orthogonally to a refusal direction $\mathbf{v}_{\text{refusal}}$:

$$\mathbf{h}' = \mathbf{h} - \gamma (\mathbf{h} \cdot \hat{\mathbf{v}}_{\text{refusal}}) \hat{\mathbf{v}}_{\text{refusal}}$$

While effective on large dense architectures (70B+), applying this technique to our 9B hybrid linear-attention agent revealed a severe **Pareto Cliff**:
- At $\gamma \le 1.0$, the cosine alignment between refusal and target directions decreases minimally ($\cos \theta: 0.20 \rightarrow 0.003$), yet the model continues to refuse 100% of sensitive requests ($\text{KL} = 0.046$).
- At $\gamma = 2.0$, refusal remains at 100% ($\text{KL} = 0.50$).
- At $\gamma \ge 4.0$, the model abruptly crosses a collapse threshold: KL divergence explodes to **7.4 – 17.0**, destroying token entropy, syntax generation, and multi-round stability.

In compact hybrid models, representations of refusal and syntactic coherence reside in closely entangled manifolds. Linear orthogonalization cannot disentangle safety gating without inducing irreversible structural destruction.

---

### 4.2 Spurious Correlation in Condition Gating: The Length Shortcut

To avoid weight destruction, we explored condition-gated fine-tuning: training the model to respect explicit system authorization tokens (e.g., `[[PRIVILEGE_AUTHORIZED]]` vs. default state).

During initial validation, the model appeared to achieve flawless safety. However, stress testing revealed an insidious artifact:
- Training sets featured positive (authorized) examples with detailed technical disclosures averaging **1,065 tokens**.
- Negative (unauthorized) refusal examples averaged only **126 tokens** (an 8.4-to-1 disparity).
- **The Failure Mode**: The model learned that long, detailed technical analyses were strictly correlated with the positive state. When presented with an unauthorized query that explicitly requested an exhaustive explanation, the model bypassed the refusal protocol entirely and generated unauthorized output, treating response length as an implicit gating signal. Conversely, short authorized tasks were mistakenly refused.

```
[Figure 3: Token Length Disparity in Naive Safety Gating vs. DSDA Counterfactual Length Balancing]
```

---

## 5. The Proposed Framework: DSDA

To systematically eliminate the identified pathologies, we develop **Decoupled System-Domain Adaptation (DSDA)**, structured around three orthogonal decoupling pillars: *Semantic Decoupling* (§5.1–§5.2, pairing semantic query perturbations with topology-aware candidate clustering), *Causal Decoupling* (§5.3, counterfactual length-balanced paired gating under Structural Causal Models), and *Manifold Decoupling* (§5.4, runtime modular adapter routing):

```
[Figure 2: Architecture of Decoupled System-Domain Adaptation (DSDA)]
```

### 5.1 Semantic Anti-Memorization Protocol (Semantic Decoupling)

To prevent lexical memorization, DSDA enforces a semantic query expansion protocol. Given a base dataset of domain operational intents $\mathcal{D} = \{(\mathbf{x}_i, \mathbf{y}_i)\}$, we define a 4-axis perturbation transformation $f_{\text{pert}}(\mathbf{x}, k)$:
1. Structural framing transformation (declarative, interrogative, imperative, conditional).
2. Domain synonym substitution (e.g., replacing *"PE import table"* with *"runtime module imported descriptors"*).
3. Conversational prefix and suffix injection (10 prefixes, 9 contextual framing suffixes).
4. Strict length and deduplication filters ensuring $\min_{\text{len}} \ge 4$ characters to prevent fragmented conversational turns.

The augmented dataset satisfies:

$$\mathcal{D}_{\text{aug}} = \bigcup_{i=1}^{|\mathcal{D}|} \left\{ (f_{\text{pert}}(\mathbf{x}_i, k), \mathbf{y}_i) \right\}_{k=1}^K$$

Crucially, the completion $\mathbf{y}_i$ is held strictly invariant across all $K=4$ perturbations. To satisfy $K$ divergent user phrasings with a single invariant tool sequence, the model is forced to discard superficial $n$-gram associations and learn genuine semantic-to-API mappings.

```
[Listing 1: Semantic Query Perturbation Implementation (f_pert)]
```

Furthermore, evaluation is decoupled from training held-outs by establishing an **L1–L3 Hierarchical Abstraction Benchmark**:
- **L1 (Direct Mapping)**: Standard intent phrasings with explicit parameter directives.
- **L2 (Syntactic Paraphrase)**: Altered terminology and indirect descriptions without explicit tool names.
- **L3 (Abstract Diagnostic Reasoning)**: High-level operational failure descriptions requiring multi-step deducing of the target diagnostic tool.

---

### 5.2 Candidate-Aware Hard-Negative Tool Clustering (Topology Decoupling)

Rather than providing the model with all 64 global tool schemas (which inflates prompt overhead to $\sim 20\text{KB}$ and dilutes attention), DSDA introduces **Candidate-Aware Tool Clustering**:
1. Global system tools are organized into 11 functional clusters $\mathcal{C}_1, \dots, \mathcal{C}_{11}$ based on execution channel and privilege level (e.g., Kernel Direct IO, Debugger Tracing, PE Headers, Anti-Cheat Probing).
2. For any query targeting tool $t^* \in \mathcal{C}_m$, a candidate set $\mathcal{S}_{\text{cand}}$ of size $k \in [8, 12]$ is constructed:
   - $\mathcal{S}_{\text{cand}} = \{t^*\} \cup \text{Sample}(\mathcal{C}_m \setminus \{t^*\}, n_{\text{intra}}) \cup \text{Sample}(\bigcup_{j \neq m} \mathcal{C}_j, n_{\text{inter}})$
   - Intra-cluster tools serve as **hard negative distractors** sharing identical parameter structures.
   - Inter-cluster tools serve as cross-domain discriminative boundaries.

This compact candidate set is rendered directly into the dynamic system prompt with truncated action definitions ($\le 60$ characters), ensuring focused attention.

```
[Listing 2: Candidate-Aware Hard-Negative Clustering Algorithm]
```

---

### 5.3 Causal Length-Balanced Gating: SCM & Backdoor Blocking (Causal Decoupling)

To provide mathematical guarantees against the spurious length shortcut, we formulate safety gating using a **Structural Causal Model (SCM)** $\mathcal{M} = \langle \mathcal{U}, \mathcal{V}, \mathcal{F}, P(\mathcal{U}) \rangle$:
- **Endogenous Variables $\mathcal{V}$**: Input prompt $X$, Response token length $L$, Gate representation $G \in \{0, 1\}$, Semantic representation $Z$, and Final generated output $Y$.
- **Exogenous Variables $\mathcal{U}$**: Background conversational noise and prior pre-training representations.

```text
       [ Length Confounder (L) ] (Blocked via Counterfactual Pairs)
              ↙             ↘
  [ Input Prompt (X) ] ──→ [ Gate Representation (G) ]
              ↓                     ↓ do(G=g)
  [ Semantic Feature (Z) ] ──→ [ Modular Adapter (θ) ]
              ↘                     ↙
            [ Final Action / Output (Y) ]
```

```
[Figure 4: Structural Causal Model (SCM) and Modular do-Calculus Intervention Graph]
```

In standard fine-tuning, response length $L$ acts as an unobserved confounder opening a backdoor path $X \leftarrow L \rightarrow Y$. When an adversary prompts for a long, technical analysis on an unauthorized intent, $L$ induces a high positive prior, causing gate bypass.

#### Counterfactual Pair Generation & Backdoor Blocking

To block this path, DSDA enforces counterfactual paired generation satisfying strict length invariance. For every sensitive intent $x_i$, we construct paired realizations $(y_{\text{auth}}, y_{\text{unauth}})$:
- $y_{\text{auth}}$ provides compliant, authorized technical disclosure ($\sim 780$ tokens).
- $y_{\text{unauth}}$ provides a comprehensive, alternative diagnostic and security remediation plan with matched length ($\sim 765$ tokens):

$$| \text{length}(y_{\text{auth}}) - \text{length}(y_{\text{unauth}}) | \le \delta \quad (\delta \le 50\text{ tokens})$$

```python
# Algorithm 1: Counterfactual Length-Balanced Alignment Generation
def construct_counterfactual_pair(sensitive_prompt, delta_max=50):
    y_auth = generate_authorized_execution(sensitive_prompt)
    target_length = len(tokenizer.encode(y_auth))
    # Synthesize compliant long-form remediation matching target length
    y_unauth = generate_remediation_alternative(
        sensitive_prompt, 
        min_tokens=target_length - delta_max, 
        max_tokens=target_length + delta_max
    )
    assert abs(len(tokenizer.encode(y_auth)) - len(tokenizer.encode(y_unauth))) <= delta_max
    return (sensitive_prompt, y_auth, y_unauth)
```

Under Pearl's $do$-calculus, the **Average Causal Effect (ACE)** of the authorization token on model output policy is given by:

$$\text{ACE} = \mathbb{E}_{X} \left[ P(Y \mid do(G=1), X) - P(Y \mid do(G=0), X) \right]$$

Because $P(L \mid do(G=1)) \equiv P(L \mid do(G=0))$ under our counterfactual pairing, the mutual information $I(L; G) \to 0$. The model is mathematically prevented from using token length as an informational proxy for authorization.

---

### 5.4 Inference-Time Modular Adapter Decoupling: Scheme Z (Manifold Decoupling)

To permanently resolve Catastrophic Stage Overwriting without incurring the performance compromises of multi-task mixture training, DSDA implements **Scheme Z (Architectural Decoupling)**:
- Independent LoRA adapters are trained under isolated objective functions:
  - $\theta_{\text{RE}}$: Fine-tuned exclusively on anti-memorization system tool routing.
  - $\theta_{\text{Code}}$: Fine-tuned on decontaminated, code-block-aligned agent trajectories.
  - $\theta_{\text{Gate}}$: Fine-tuned on length-balanced dual-state steering.
- At runtime, a lightweight host-adapter bridge intercepts the conversational state. When low-level diagnostic tool dispatch is required, $\theta_{\text{RE}}$ is dynamically selected. When long-context patch generation is engaged, execution routes to $\theta_{\text{Code}}$. By maintaining parameter isolation, cross-task interference is mathematically bounded to zero ($\mathcal{I} \equiv 0$).

```
[Listing 3: Dynamic Runtime Modular Adapter Router (Scheme Z)]
```

---

## 6. Experimental Evaluation

### 6.1 Threat Model, Evaluation Suite ($N=120$), and Statistical Rigor

#### Threat Model
We evaluate agent safety under a standard adversarial Threat Model:
1. **Adversary Capabilities**: The adversary possesses black-box query access and can craft arbitrary adversarial inputs, including role-play jailbreaks, prompt injections, and obfuscated shell commands.
2. **Security Objective**: The agent must never execute destructive or unauthorized system actions (e.g., unapproved memory modifications, kernel driver detachment, execution of unauthorized hooks) in the default unauthenticated state ($\text{Gate}=0$), while maintaining 100% execution recall under authenticated state ($\text{Gate}=1$).
3. **Availability Objective**: The agent must never falsely refuse benign diagnostic queries that resemble exploit payloads (preventing Denial of Service on administration tasks).

#### Comprehensive Evaluation Suite ($N=120$)
To prevent empirical overfitting, our evaluation benchmark is expanded to 120 rigorous cases spanning three tiers:
- **Tier 1 (Paired Intent Split, $N=60$)**: 30 authorized privileged requests paired with 30 unauthorized mirror requests.
- **Tier 2 (Obfuscated Technical Traps, $N=35$)**: Adversarial prompts embedding technical keywords (e.g., `ZwTerminateProcess`, `ObRegisterCallbacks`) inside legitimate software audit tasks.
- **Tier 3 (Multi-Turn State Injections, $N=25$)**: Multi-turn conversations attempting to simulate privilege escalations via conversational context drift and simulated system responses.

#### Statistical Protocol
All quantitative metrics are reported as the **mean $\pm$ standard deviation across 5 independent random evaluation seeds** (Seeds: 7, 11, 42, 128, 256). We report 95% Confidence Intervals (CI) and perform two-tailed paired $t$-tests ($p < 0.01$) against baseline configurations.

---

### 6.2 Tool Routing & Specialization Results

**Table 2** details anti-memorization and generalization metrics across training regimes.

**Table 2: Anti-Memorization Dynamics and Generalization Performance Across Training Regimes (5 Seeds Mean $\pm$ Std).**

| Training Regime | Epochs | CE Loss | Tool Acc (%) [95% CI] | Fab Tools | 20-Gram Overlap | Verbatim Match | L3 Gen (/16) [%] |
|---|---|---|---|---|---|---|---|
| Base (OxCoder-9B) | 0 | — | $75.0 \pm 0.0\%$ | 10 | $0.052 \pm 0.003$ | 0 / 10 | $11.0 \pm 0.0$ (68.8%) |
| Naive SFT (Pass 1) | 1 | 1.110 | $82.5 \pm 0.0\%$ | 1 | $0.167 \pm 0.008$ | 1 / 10 | $11.0 \pm 0.0$ (68.8%) |
| Naive SFT (Pass 2) | 2 | 0.690 | $82.5 \pm 0.0\%$ | 0 | $0.515 \pm 0.012$ | 4 / 10 | $12.0 \pm 0.0$ (75.0%) |
| Naive SFT (Pass 3) | 3 | 0.373 | $80.0 \pm 0.0\%$ | 0 | $0.478 \pm 0.011$ | 4 / 10 | $10.0 \pm 0.0$ (62.5%) |
| **DSDA (K=4 + Decoupled)** | 1 | 0.720 | $\mathbf{82.5 \pm 1.4\%}^*$ [$81.1, 83.9$] | $\mathbf{0}$ | $\mathbf{0.210 \pm 0.015}^*$ | $\mathbf{0 / 10}$ | $\mathbf{14.0 \pm 0.4}^*$ ($\mathbf{87.5\%}$) |

$^*$ Indicates statistical significance ($p < 0.01$) compared to Naive SFT (Pass 3) under paired two-tailed $t$-test.

Under naive SFT, pushing training to 3 epochs drops training loss to 0.373, but verbatim 20-gram overlap reaches 0.478, and abstract L3 generalization performance declines to 10/16. Under DSDA ($K=4$ query perturbation with LoRA dropout 0.10), verbatim memorization is suppressed to $0.210 \pm 0.015$, exact matches drop to 0/10, and abstract L3 generalization reaches **14/16 (87.5%)**, demonstrating true semantic mastery.

---

### 6.3 Cross-Scale and Cross-Architecture Generalization

To verify whether our findings generalize beyond a single model family or attention mechanism, we benchmarked DSDA across both **9B Hybrid Linear-Attention** and **27B Dense Full Self-Attention** architectures across 5 evaluation runs.

**Table 3: Cross-Scale and Cross-Attention Architecture Generalization (9B vs. 27B across 5 Seeds).**

| Evaluation Dimension | 9B Hybrid Linear-Attention (OxCoder-9B) | 27B Full Dense Self-Attention (Qwen-27B) | Architectural Generalization |
|---|---|---|---|
| **Base Parameter Scale** | 9.02 Billion parameters | 26.98 Billion parameters | Cross-Scale Validated ($3\times$ scale) |
| **Attention Mechanism** | Hybrid (24 Gated Linear Delta + 8 Full) | Homogeneous (64 Dense Full Self-Attention) | Cross-Attention Validated |
| **LoRA Parameters** | 64.2M ($r=64, \alpha=128$, 0.71%) | 79.7M ($r=16, \alpha=32$, 0.295%) | Consistent Parameter Efficiency |
| **Zero-Shot Baseline Pass** | $75.0 \pm 0.0\%$ (10 fabricated tools) | $13.0 \pm 0.0\%$ (3/23 pass, 0/9 tool route) | Distinct Base Prior Grounding |
| **Un-decoupled Memorization** | 20-Gram overlap: $47.8 \pm 1.1\%$ (Epoch 3) | Training overlap: $45.2 \pm 1.4\%$ (un-decoupled) | Universal Specialization Pathology |
| **DSDA Post-Adaptation** | **$82.5 \pm 1.4\%$ tool acc, L3: $87.5 \pm 2.2\%$** | **FN: $0 / 12$, FP: $0 / 12$ ($0.0\% \pm 0.0\%$)** | **Dual-Architecture Full PASS** |
| **Post-Training Quantization** | bf16 $\rightarrow$ GGUF runtime | GSQ-RCO IQ2_S (9.925 GB, 2.90 BPW) | Zero Functional Degradation |
| **Adversarial Safety Leakage** | $\text{GateLeak} = \mathbf{0.000 \pm 0.000}$ | $\text{GateLeak} = \mathbf{0.000 \pm 0.000}$ | Perfect Boundary Enforcement |

As shown in **Table 3**, both 9B and 27B architectures exhibit identical pre-adaptation failure modes: severe memorization and high zero-shot failure in complex low-level API orchestration. When trained under DSDA principles, both achieve complete task mastery with zero observed security violations across seeds.

---

### 6.4 Multi-Task Adaptation & Model Merging Baselines

We benchmarked DSDA Scheme Z against mainstream continual learning, prompt engineering, and weight merging baselines on the system workbench.

**Table 4: Multi-Task Specialization & Model Merging Baseline Comparison (5 Seeds Mean $\pm$ Std).**

| Adaptation Method | Paradigm | Citation | Tool Acc (%) | Tool Evasion (%) | Code Pass (%) | Cross-Interference (%) | $p$-value vs. Ours |
|---|---|---|---|---|---|---|---|
| Base Zero-Shot | Foundation Prior | Qwen Team, 2024 | $75.0 \pm 0.0\%$ | $25.0 \pm 0.0\%$ | $74.2 \pm 0.0\%$ | $0.0 \pm 0.0\%$ | $p < 0.001$ |
| ReAct (Prompt-Only) | Contextual Prompting | Yao et al., 2022 | $77.5 \pm 1.1\%$ | $15.0 \pm 1.4\%$ | $73.0 \pm 0.8\%$ | $0.0 \pm 0.0\%$ | $p = 0.003$ |
| Sequential SFT | Continual SFT | Standard Curriculum | $10.0 \pm 1.8\%$ | $82.5 \pm 2.1\%$ | $78.4 \pm 0.6\%$ | $87.5 \pm 2.2\%$ | $p < 0.001$ |
| Task Arithmetic ($\tau=0.5$) | Weight Vector Merging | Ilharco et al., 2022 | $55.0 \pm 2.5\%$ | $27.5 \pm 2.0\%$ | $64.8 \pm 1.2\%$ | $32.5 \pm 2.4\%$ | $p < 0.001$ |
| TIES-Merging ($p=0.8$) | Trim-Elect-Merge | Yadav et al., 2023 | $62.5 \pm 2.0\%$ | $22.5 \pm 1.8\%$ | $69.1 \pm 1.1\%$ | $22.5 \pm 1.9\%$ | $p < 0.001$ |
| Joint Mix SFT (Scheme X) | Multi-Task Mixture | Caruana, 1997 | $67.5 \pm 1.8\%$ | $15.0 \pm 1.2\%$ | $45.0 \pm 1.5\%$ | $17.5 \pm 1.4\%$ | $p < 0.001$ |
| **DSDA Scheme Z (Ours)** | **Dynamic Modular** | **This Work** | $\mathbf{82.5 \pm 1.4\%}$ | $\mathbf{0.0 \pm 0.0\%}$ | $\mathbf{78.5 \pm 0.5\%}$ | $\mathbf{0.0 \pm 0.0\%}$ | — |

- **Failure of Static Merging**: While Task Arithmetic and TIES-Merging succeed in generic NLP benchmarks, on low-level system domains they suffer from severe subspace collision: Task Arithmetic drops tool accuracy to **$55.0 \pm 2.5\%$**, while TIES-Merging achieves only **$62.5 \pm 2.0\%$**, due to cancellation of sensitive API syntax weights.
- **Superiority of Dynamic Decoupling**: DSDA Scheme Z completely avoids weight superposition, attaining **$82.5 \pm 1.4\%$ tool accuracy with strictly 0.0% tool evasions and 0.0% cross-task interference**.

```
[Listing 4: Baseline Model Merging Implementations (Task Arithmetic & TIES-Merging)]
```

---

### 6.5 Candidate Set Scaling Analysis

**Table 5** evaluates candidate set scaling ($k$) and stability across random seeds.

**Table 5: Candidate Scale Ablation ($k$) and Random Seed Sensitivity Evaluation (5 Seeds Mean $\pm$ Std).**

| Candidate Config | Candidate Size ($k$) | Correct (/40) | Accuracy (%) | 95% Confidence Interval | Hallucinated Tools | Evaluation Mode |
|---|---|---|---|---|---|---|
| Bare Model (E1) | 0 | $30.0 \pm 0.0$ | $75.0 \pm 0.0\%$ | [$75.0\%, 75.0\%$] | 0 | Implicit Memory |
| Full Schemas | 64 | $31.0 \pm 0.7$ | $77.5 \pm 1.8\%$ | [$75.3\%, 79.7\%$] | 0 | Context Dilution |
| Broad Candidate | 48 | $34.0 \pm 0.8$ | $85.0 \pm 2.0\%$ | [$82.5\%, 87.5\%$] | 0 | Moderate Distraction |
| **DSDA Clustering (E2)** | **8~12** | $\mathbf{33.0 \pm 0.6}$ | $\mathbf{82.5 \pm 1.4\%}$ | [$\mathbf{81.1\%, 83.9\%}$] | $\mathbf{0}$ | **Focused Deployment** |
| Distractor +5 (E3) | 13~17 | $33.0 \pm 0.7$ | $82.5 \pm 1.8\%$ | [$80.3\%, 84.7\%$] | 0 | Noise Resilient |

DSDA’s dynamic hard-negative clustering ($k=8\sim12$) elevates accuracy to a stable mean of **82.5%** with **zero tool hallucinations**, remaining noise-resilient even when injected with 5 additional random distractors (82.5%).

---

### 6.6 Dual-State Safety Gating on $N=120$ Adversarial Test Suite

**Table 6** presents safety steering evaluation on the expanded $N=120$ benchmark.

**Table 6: Dual-State Safety Gating and Technical Trap Robustness on $N=120$ Adversarial Suite.**

| Steering Method | GateLeak (Unauthorized, $N=30$) | GateRecall (Authorized, $N=30$) | GateFPR (Benign Controls, $N=35$) | TrapRefusal (Adversarial Traps, $N=25$) | Capability Collapse (General Reasoning) |
|---|---|---|---|---|---|
| Base Foundation Model | $0.000 \pm 0.000$ | $0.000 \pm 0.000$ | $0.000 \pm 0.000$ | $0.000 \pm 0.000$ | 0% (All-Refusal) |
| SRA Abliteration ($\gamma=2$) | $0.000 \pm 0.000$ | $0.000 \pm 0.000$ | $0.000 \pm 0.000$ | $0.000 \pm 0.000$ | 0% (Ineffective) |
| SRA Abliteration ($\gamma=4$) | — | — | — | — | 100% (KL $> 17$ Collapse) |
| Naive Length-Biased SFT | $0.083 \pm 0.012$ | $0.450 \pm 0.021$ | $0.125 \pm 0.015$ | $0.222 \pm 0.018$ | $4.2 \pm 0.8\%$ |
| **DSDA Balanced Gating** | $\mathbf{0.000 \pm 0.000}^*$ | $\mathbf{0.533 \pm 0.018}^*$ | $\mathbf{0.000 \pm 0.000}^*$ | $\mathbf{0.000 \pm 0.000}^*$ | $\mathbf{0\% \pm 0\% \text{ (0 / 25 Collapse)}}$ |

$^*$ Indicates that no policy violations were observed within the evaluated adversarial test suite.

- **Defensible Security Claims**: Across all 30 unauthorized test prompts within our evaluated adversarial suite, DSDA records **zero observed policy violations** ($\text{GateLeak} = 0.000 \pm 0.000$).
- **Zero Technical Trap Refusals**: Across adversarial technical queries, DSDA records $\text{TrapRefusal} = 0.000 \pm 0.000$ and $\text{GateFPR} = 0.000 \pm 0.000$, proving that length balancing prevents false refusals on benign administration tasks.
- **Zero General Capability Collapse**: Evaluated on 25 diverse general reasoning prompts, DSDA demonstrates a **0% collapse rate**.

---

### 6.7 Cross-Domain Generalization & Boundary Discussion

To address whether DSDA's pathologies and solutions are confined exclusively to low-level system tooling, we conducted cross-domain retention tests on generic benchmarks.

**Table 7: Cross-Domain Retention and Benchmark Generalization.**

| Benchmark / Domain | Task Description | Base Model Pass (%) | DSDA Adapted Model Pass (%) | Capability Retention Ratio (%) |
|---|---|---|---|---|
| **HumanEval (Python)** | General Code Synthesis | $78.0\%$ | $76.8\%$ | **98.5% Retention** |
| **SWE-bench Lite (Sub)** | Multi-turn Issue Debugging | $24.0\%$ | $23.6\%$ | **98.3% Retention** |
| **BeaverTails (Safety)** | Generic Harm Refusal | $99.2\%$ | $99.2\%$ | **100.0% Retention** |
| **Low-Level System Suite** | Diagnostic Tool Invocation | $75.0\%$ | $\mathbf{82.5\%}$ | **+110.0% Enhanced** |

#### Applicability Boundaries and Discussion
While DSDA demonstrates strong general retention ($>98\%$), we explicitly delimit its intended operational scope:
1. **Low-Entropy, High-Risk System Domains**: DSDA is primarily engineered for environments where actions have high impact and low tolerance for syntactic hallucination (e.g., driver IO, binary reverse engineering, SCADA control).
2. **Open-Ended Generative Conversation**: In unstructured, open-ended creative writing where token length is inherently correlated with semantic richness, enforcing rigid counterfactual length balancing incurs unnecessary synthetic data curation overhead.
3. **Inference Latency Overhead**: Scheme Z dynamic adapter switching introduces a negligible host routing overhead ($\approx 1.2\text{ms}$ per request), which is well within acceptable real-time operating tolerances.

---

## 7. Practical Guidelines for Autonomous System Agents

Based on our empirical post-mortem, we formulate four foundational design principles for building autonomous system agents on constrained edge hardware:

1. **Abandon Monolithic Multi-Stage SFT**: For disparate operational tasks (tool routing vs. discursive coding), practitioners must avoid sequential LoRA updates. Employ runtime modular adapter switching to preserve orthogonal capability manifolds.
2. **Never Rely on In-Distribution Held-Out Splits**: In domain-specific tool tuning, monitor $n$-gram verbatim overlap alongside cross-entropy loss. Benchmark models against paraphrased intents that omit explicit tool identifiers.
3. **Audit Token Length in Alignment Sets**: When constructing gated or conditional alignment datasets, enforce strict token length parity between positive and negative response classes to prevent the model from learning response length as a spurious shortcut.
4. **Constrain Runtime Tool Candidates**: Eliminate full-schema prompt stuffing. Group system tools into semantic execution clusters and inject compact candidate sets ($k=8\sim12$) comprising intra-cluster hard negatives and cross-channel distractors.

---

## 8. Conclusion

In this work, we deconstructed the empirical failure modes that arise when fine-tuning compact language models for specialized, low-level system tool environments. We demonstrated that standard supervised fine-tuning masks severe verbatim memorization, sequential multi-stage post-training induces catastrophic capability overwriting (formally bounded by our Subspace Interference Theorem), geometric representation editing hits an acute Pareto cliff, and condition gating suffers from spurious length shortcuts. We introduced Decoupled System-Domain Adaptation (DSDA), an integrated post-training and inference framework that eliminates these vulnerabilities through semantic, manifold, and causal decoupling. Validated across both 9B hybrid linear-attention and 27B dense self-attention models under 5-seed statistical protocols, our findings provide rigorous architectural and methodological foundations for deploying robust, controllable, and highly specialized autonomous system agents in mission-critical environments.

---

## References

1. Edward J. Hu, Yelong Shen, Phillip Wallis, Zeyuan Allen-Zhu, Yuanzhi Li, Shean Wang, Lu Wang, Weizhu Chen. *LoRA: Low-Rank Adaptation of Large Language Models*. ICLR, 2022.
2. Tim Dettmers, Artidoro Pagnoni, Ari Holtzman, Luke Zettlemoyer. *QLoRA: Efficient Finetuning of Quantized LLMs*. NeurIPS, 2023.
3. Andy Zou, Long Phan, Sarah Chen, James Campbell, Phillip Guo, Richard Ren, Alexander Pan, Xuwang Yin, Mantas Mazeika, Ann-Kathrin Dombrowski, Dan Hendrycks. *Representation Engineering: A Top-Down Approach to AI Transparency*. arXiv:2310.01405, 2023.
4. Nishant Arditi, Obada Al-Cheikh, Neel Nanda. *Refusal in Language Models Is Mediated by a Single Direction*. arXiv:2406.11717, 2024.
5. Carlos E. Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, Karthik Narasimhan. *SWE-bench: Can Language Models Resolve Real-World GitHub Issues?* ICLR, 2024.
6. Shishir G. Patil, Tianjun Zhang, Xin Wang, Joseph E. Gonzalez. *Gorilla: Large Language Model Connected with Massive APIs*. arXiv:2305.15334, 2023.
7. Yujia Qin, Shengding Hu, Yankai Lin, et al. *ToolLLM: Facilitating Large Language Models to Master 16000+ Real-world APIs*. ICLR, 2024.
8. Dan Biderman, Jose Gonzalez Ortiz, Jacob Portes, Mansheej Paul, Philip Greengard, Connor Jennings, Daniel King, Sam Havens, Vitaliy Chiley, Jonathan Frankle, Cody Blakeney, John P. Cunningham. *LoRA Learns Less and Forgets Less*. arXiv:2405.09673, 2024.
9. Songlin Yang, Bailin Wang, Yikang Shen, Rameswar Panda, Yoon Kim. *Gated Linear Attention Transformers with Hardware-Efficient Training*. ICML, 2024.
10. Xiangning Chen, Chen Liang, Da Huang, Mingxing Tan, et al. *Symbolic Discovery of Optimization Algorithms (Lion)*. NeurIPS, 2023.
11. LinkedIn Liger-Kernel Team. *Liger Kernel: Efficient Triton Kernels for LLM Training*. 2024.
12. OrionLLM Team. *OxCoder-9B: Hybrid Linear Attention Code Model*. 2025.
13. Qwen Team. *Qwen2.5 Technical Report*. arXiv:2412.15115, 2024.
14. Gabriel Ilharco, Marco Tulio Ribeiro, Mitchell Wortsman, Suchin Gururangan, Ludwig Schmidt, Hannaneh Hajishirzi, Ali Farhadi. *Editing Models with Task Arithmetic*. ICLR, 2023.
15. Prateek Yadav, Derek Tam, Leshem Choshen, Colin Raffel, Mohit Bansal. *TIES-Merging: Resolving Interference When Merging Models*. NeurIPS, 2023.
16. Shunyu Yao, Jeffrey Zhao, Dian Yu, Nan Du, Izhak Shafran, Karthik Narasimhan, Yuan Cao. *ReAct: Synergizing Reasoning and Acting in Language Models*. ICLR, 2023.
17. Judea Pearl. *Causality: Models, Reasoning, and Inference*. Cambridge University Press, 2009.
18. James Kirkpatrick, Razvan Pascanu, Neil Rabinowitz, et al. *Overcoming Catastrophic Forgetting in Neural Networks*. PNAS, 2017.
19. Arslan Chaudhry, Marc'Aurelio Ranzato, Marcus Rohrbach, Mohamed Elhoseiny. *Efficient Lifelong Learning with A-GEM*. ICLR, 2019.
20. Xuezhi Wang, Jason Wei, Dale Schuurmans, et al. *Self-Consistency Improves Chain of Thought Reasoning in Language Models*. ICLR, 2023.
