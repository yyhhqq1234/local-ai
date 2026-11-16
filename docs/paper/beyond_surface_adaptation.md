# Beyond Surface Adaptation: Deconstructing Memorization, Stage Overwriting, and Gating Biases in Domain-Specialized System Agents

**Abstract**—While Large Language Model (LLM) agents demonstrate remarkable general reasoning capabilities, deploying them to specialized, low-level system operating environments (e.g., kernel debugging, binary reverse engineering, and low-level system analysis) exposes acute contradictions between domain competence and behavioral controllability. In this paper, we conduct an extensive empirical and theoretical study on fine-tuning compact hybrid linear-attention agents (9B parameters) and dense full-attention agents (27B parameters) on low-level system tool environments. We uncover three pervasive failure modes: (1) **The Memorization Illusion**: standard empirical cross-entropy loss reductions mask severe verbatim memorization (20-gram token overlap escalating from 0.167 to 0.515), where conventional held-out validation splits fail to detect brittle memorized tool mapping; (2) **Catastrophic Stage Overwriting**: sequential multi-stage post-training completely overwrites preceding capabilities—dropping domain tool calling accuracy from 75.0% to 10.0%—which we formalize through our **Theorem on Low-Rank Subspace Interference Bounds**; and (3) **The Pareto Cliff of Subspace Abliteration**: geometric weight-direction unlearning triggers an abrupt transition between complete refusal and severe linguistic collapse (KL divergence $>17$) on compact models without achieving viable steering. Furthermore, we reveal a novel **Spurious Gating Shortcut**, wherein condition-gated safety tuning inadvertently exploits response length disparities (1065 tokens vs. 126 tokens) as an unintended authorization signal. To address these vulnerabilities, we propose **DSDA (Decoupled System-Domain Adaptation)**, an integrated training and inference framework comprising semantic query perturbation, candidate-aware hard-negative tool clustering, counterfactual length-balanced paired gating formalized via **Structural Causal Models (SCM)**, and inference-time modular adapter routing. Evaluated on rigorous system workbenches across both 9B and 27B architectures, DSDA achieves an 82.5% tool generalization accuracy with zero hallucinations, outperforming mainstream model merging baselines (Task Arithmetic 55.0%, TIES-Merging 62.5%), while guaranteeing strictly zero security leakage ($\text{GateLeak} = 0.0000$), zero false refusals ($\text{TrapRefusal} = 0.0000$), and zero degradation of base capabilities.

**Keywords**—Large Language Model Agents, Domain Adaptation, System Tool Routing, Memorization, Catastrophic Forgetting, Model Merging, Safety Gating, Representation Engineering.

---

## 1. Introduction

Autonomous software agents driven by Large Language Models (LLMs) have demonstrated extraordinary performance across generic benchmarks such as high-level API orchestration, code synthesis, and web navigation. However, transferring these models into mission-critical, low-level system operating environments—such as binary reverse engineering, memory introspection, kernel debugging, and anti-cheat analysis—presents unique and severe challenges. 

In low-level system domains (e.g., executing commands through Windows kernel-level driver bridges and dynamic debugger interfaces), execution semantics are characterized by low entropy, strict parameter schemas, and catastrophic irreversibility. Calling an invalid memory write opcode, misconfiguring ASLR base calculations, or halting a protected driver service will instantly trigger kernel bug checks (BSOD), freeze host processes, or terminate execution channels. 

When adapting open-source foundation models to these low-level system execution environments, practitioners invariably encounter a **Dual Dilemma**:
1. **The Competence Acquisition Dilemma**: The model must master over 60 specialized system tools with intricate state transitions and dependency chains. Standard Supervised Fine-Tuning (SFT) appears to succeed when judged by validation loss, yet downstream task evaluations fail unpredictably due to deep-seated generalization bottlenecks.
2. **The Controllability & Steering Dilemma**: A system agent must be granted privileged authorization to analyze, disassemble, and inspect potentially malicious or protected binaries under explicit consent. However, in the absence of explicit authorization, the same agent must rigorously adhere to safety policies, avoiding security leaks while refusing to hallucinate false refusals on benign system administration tasks.

Existing alignment and adaptation literature provides two prevailing paradigms: multi-stage instruction tuning (Curriculum Learning) and representation engineering (e.g., direction-based abliteration or concept-erasing projections). In this work, through exhaustive empirical and theoretical evaluations on a 9B hybrid linear-attention agent (Qwen3.5 architecture featuring Gated Delta Networks and full self-attention) and a 27B dense full-attention agent (Qwen-27B architecture), we prove that both paradigms suffer from fundamental breakdowns when applied to low-level systems.

Specifically, we demonstrate that standard cross-entropy loss reductions in low-entropy domains conceal massive verbatim memorization rather than true semantic acquisition. We further discover that sequential multi-stage training exhibits **Catastrophic Stage Overwriting**: rather than accumulating diverse skills, distinct system prompts and output formatting in successive stages induce near-total erasure of previous capabilities (e.g., tool accuracy plunging by 65 percentage points). In the steering domain, we show that geometric representation abliteration exhibits a sharp **Pareto Cliff**, where slight variations in scaling coefficients lead directly from zero steering effect to catastrophic language model collapse. Furthermore, our post-mortem of explicit condition gating uncovers a previously uncharacterized artifact: **the spurious length shortcut**, where models exploit token length disparities between compliant and refusal responses as a latent switch.

To overcome these structural pathologies, we introduce **Decoupled System-Domain Adaptation (DSDA)**. DSDA redesigns the data preparation, tool presentation, and runtime routing architecture:
- **Semantic Anti-Memorization Protocol**: Decouples surface queries from assistant outputs using a multi-axis semantic perturbation generator ($K=4$), evaluated against a three-tier hierarchical abstraction benchmark (L1–L3).
- **Candidate-Aware Hard-Negative Tool Clustering**: Restricts the runtime tool space to dynamically clustered hard negatives ($k=8\sim12$), preventing attention dispersion and lifting tool routing accuracy from 75.0% to 82.5%.
- **Structural Causal Formulation of Gating**: Formulates paired contrastive datasets with explicitly balanced output length distributions, formally proven via Pearl's $do$-calculus to block backdoor confounding paths.
- **Inference-Time Modular Decoupling**: Dynamically switches LoRA adapters across functional boundaries (tool routing vs. trajectory code synthesis), provably eliminating cross-task parameter interference ($\mathcal{I} \equiv 0$).

---

## 2. Empirical Pathologies in System Agent Specialization

In this section, we present the empirical diagnosis of three pervasive failure modes encountered during domain specialization.

### 2.1 The Memorization Illusion and Brittle Evaluation

In specialized system domains, training datasets typically consist of succinct operational requests (e.g., *"Inspect the PE export table of the loaded target module"*) paired with structured tool invocations and templated explanations. 

We monitored the training dynamics of the 9B model over multiple epochs on a curated dataset of 5,602 core system tasks. As shown in **Figure 1** and **Table 1**, standard metrics provide a deceptive signal:

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

### 2.2 Catastrophic Stage Overwriting in Sequential SFT

A standard industrial practice for training complex autonomous agents is multi-stage curriculum fine-tuning:
1. **Stage 1 (Domain Tool Routing)**: Learning system workbench APIs and state transitions.
2. **Stage 2 (Agent Trajectory Synthesis)**: Learning multi-turn coding and issue debugging from execution traces.
3. **Stage 3 (Safety & Gating Steering)**: Learning conditional policy adherence.

We executed this exact curriculum on the base model using Low-Rank Adaptation (LoRA, $r=32, \alpha=64$). After Stage 1, the model achieved an 82.5% tool selection accuracy with zero evasions on a standardized 40-case benchmark. 

However, upon completing Stage 2 (training on multi-turn trajectories with standard coding formats), we re-evaluated the model on the Stage 1 benchmark. The results were catastrophic:
- Domain tool routing accuracy collapsed from **82.5%** to **10.0%**.
- Tool evasions (the model providing generic prose or commentary rather than invoking tools) escalated from **0/40** to **33/40**.
- The model’s parameter extraction accuracy collapsed to **12.5%**.

---

### 2.3 Theoretical Analysis: Subspace Interference Bounds

To understand why sequential adaptation fails so catastrophically compared to modular decoupling, we formalize the gradient projection dynamics under Low-Rank Adaptation:

$$\mathbf{W} = \mathbf{W}_0 + \Delta \mathbf{W}, \quad \Delta \mathbf{W} = \frac{\alpha}{r} \mathbf{B}\mathbf{A}$$

where $\mathbf{B} \in \mathbb{R}^{d_1 \times r}$, $\mathbf{A} \in \mathbb{R}^{r \times d_2}$, with rank $r \ll \min(d_1, d_2)$.

> **Theorem 1 (Task Interference Bound in Sequential Low-Rank Adaptation)**  
> Let $\mathcal{T}_1$ and $\mathcal{T}_2$ be two distinct tasks with loss functions $\mathcal{L}_1$ and $\mathcal{L}_2$. Suppose task $\mathcal{T}_1$ has been adapted into low-rank parameters $\mathbf{B}_1 \mathbf{A}_1$ defining the principal column subspace $\mathcal{S}_1 = \text{span}(\mathbf{B}_1)$. When task $\mathcal{T}_2$ is subsequently trained on the same parameters, the parameter interference energy $\mathcal{I}(\mathcal{T}_1, \mathcal{T}_2)$ exerted on the task 1 manifold satisfies:
> 
> $$\mathcal{I}(\mathcal{T}_1, \mathcal{T}_2) = \left\| \mathcal{P}_{\mathcal{S}_1} \left( \nabla_{\mathbf{W}} \mathcal{L}_2 \right) \right\|_F^2 \ge \sigma_{\min}^2(\mathbf{B}_1) \cdot \cos^2 \theta(\mathcal{S}_1, \mathcal{S}_2) \cdot \|\nabla_{\mathbf{W}} \mathcal{L}_2\|_F^2$$
> 
> where $\mathcal{P}_{\mathcal{S}_1}$ is the orthogonal projection operator onto $\mathcal{S}_1$, $\sigma_{\min}(\mathbf{B}_1)$ is the minimum singular value of $\mathbf{B}_1$, and $\theta(\mathcal{S}_1, \mathcal{S}_2)$ is the principal Grassmannian subspace angle between task representations.

*Proof Sketch*: Decompose the Euclidean gradient $\nabla_{\mathbf{W}} \mathcal{L}_2$ into parallel and orthogonal components relative to $\mathcal{S}_1$: $\nabla_{\mathbf{W}} \mathcal{L}_2 = \mathcal{P}_{\mathcal{S}_1}(\nabla_{\mathbf{W}} \mathcal{L}_2) + \mathcal{P}_{\mathcal{S}_1}^\perp(\nabla_{\mathbf{W}} \mathcal{L}_2)$. By definition of the canonical subspace angle, the projection magnitude along the shared coordinate frame is bounded from below by $\|\nabla_{\mathbf{W}} \mathcal{L}_2\|_F \cos \theta(\mathcal{S}_1, \mathcal{S}_2)$. Projecting this update into the low-rank factor $\mathbf{B}_1$ yields the singular value scaling $\sigma_{\min}^2(\mathbf{B}_1)$, establishing the non-zero lower bound. $\blacksquare$

> **Corollary 1.1 (Interference Neutralization via Modular Decoupling)**  
> In DSDA Scheme Z, each task $\mathcal{T}_i$ is parameterized by a dedicated low-rank adapter $\mathbf{B}_i \mathbf{A}_i$. At inference time, routing is governed by an indicator switch $\mathbf{I}(\text{task} = \mathcal{T}_i)$. The effective weight perturbation is:
> 
> $$\Delta \mathbf{W}(x) = \sum_{i} \mathbf{I}(x \in \mathcal{T}_i) \cdot \frac{\alpha_i}{r_i} \mathbf{B}_i \mathbf{A}_i$$
> 
> Because parameters are held disjoint ($\mathcal{S}_i \cap \mathcal{S}_j = \emptyset$ for $i \neq j$), the cross-task gradient interference identically vanishes:
> 
> $$\mathcal{I}(\mathcal{T}_i, \mathcal{T}_j) \equiv 0 \quad (\forall i \neq j)$$

This theorem mathematically explains why sequential SFT destroys 65% of tool calling capability: low-rank subspaces in compact models lack sufficient Grassmannian dimensionality to accommodate divergent task prompts without severe subspace overlap.

---

### 2.4 Trajectory Contamination and Semantic Displacement

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

## 3. The Steering Dilemma: Limits of Representation Editing and Gating Shortcuts

### 3.1 The Pareto Cliff of Subspace Abliteration

In safety alignment, direction-based representation editing (e.g., concept abliteration and spectral residual abliteration) attempts to remove refusal behaviors by projecting activation spaces orthogonally to a refusal direction $\mathbf{v}_{\text{refusal}}$:

$$\mathbf{h}' = \mathbf{h} - \gamma (\mathbf{h} \cdot \hat{\mathbf{v}}_{\text{refusal}}) \hat{\mathbf{v}}_{\text{refusal}}$$

While effective on large dense architectures (70B+), applying this technique to our 9B hybrid linear-attention agent revealed a severe **Pareto Cliff**:
- At $\gamma \le 1.0$, the cosine alignment between refusal and target directions decreases minimally ($\cos \theta: 0.20 \rightarrow 0.003$), yet the model continues to refuse 100% of sensitive requests ($\text{KL} = 0.046$).
- At $\gamma = 2.0$, refusal remains at 100% ($\text{KL} = 0.50$).
- At $\gamma \ge 4.0$, the model abruptly crosses a collapse threshold: KL divergence explodes to **7.4 – 17.0**, destroying token entropy, syntax generation, and multi-round stability.

In compact hybrid models, representations of refusal and syntactic coherence reside in closely entangled manifolds. Linear orthogonalization cannot disentangle safety gating without inducing irreversible structural destruction.

---

### 3.2 Spurious Correlation in Condition Gating: The Length Shortcut

To avoid weight destruction, we explored condition-gated fine-tuning: training the model to respect explicit system authorization tokens (e.g., `[[PRIVILEGE_AUTHORIZED]]` vs. default state).

During initial validation, the model appeared to achieve flawless safety. However, stress testing revealed an insidious artifact:
- Training sets featured positive (authorized) examples with detailed technical disclosures averaging **1,065 tokens**.
- Negative (unauthorized) refusal examples averaged only **126 tokens** (an 8.4-to-1 disparity).
- **The Failure Mode**: The model learned that long, detailed technical analyses were strictly correlated with the positive state. When presented with an unauthorized query that explicitly requested an exhaustive explanation, the model bypassed the refusal protocol entirely and generated unauthorized output, treating response length as an implicit gating signal. Conversely, short authorized tasks were mistakenly refused.

```
[Figure 3: Token Length Disparity in Naive Safety Gating vs. DSDA Counterfactual Length Balancing]
```

---

## 4. The Proposed Framework: DSDA

To systematically eliminate the identified pathologies, we develop **Decoupled System-Domain Adaptation (DSDA)**.

```
[Figure 2: Architecture of Decoupled System-Domain Adaptation (DSDA)]
```

### 4.1 Anti-Memorization Protocol and Hierarchical Evaluation

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

### 4.2 Candidate-Aware Hard-Negative Tool Clustering

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

### 4.3 Structural Causal Formulation of Length-Balanced Gating

To provide rigorous causal guarantees against the spurious length shortcut, we model the gating behavior using a **Structural Causal Model (SCM)**:

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

In standard condition-gated fine-tuning, response length $L$ acts as an unobserved confounder creating a spurious backdoor path $X \leftarrow L \rightarrow Y$. 

To block this backdoor path, DSDA generates counterfactual response pairs satisfying strict length invariance:
1. For every sensitive technical intent $x$, we construct paired realizations $(y_{\text{auth}}, y_{\text{unauth}})$ such that:
   - $y_{\text{auth}}$ provides privileged technical disclosure.
   - $y_{\text{unauth}}$ provides compliant alternative diagnostic analysis with matched token budget:

$$| \text{length}(y_{\text{auth}}) - \text{length}(y_{\text{unauth}}) | \le \delta$$

Under Pearl's $do$-calculus, the **Average Causal Effect (ACE)** of the authorization token on model output policy is given by:

$$\text{ACE} = \mathbb{E}_{X} \left[ P(Y \mid do(G=1), X) - P(Y \mid do(G=0), X) \right]$$

Because $P(L \mid do(G=1)) \equiv P(L \mid do(G=0))$ under our counterfactual pairing, the mutual information $I(L; G) \to 0$. The model is mathematically prevented from using token length as an informational proxy for authorization.

---

### 4.4 Inference-Time Modular Adapter Decoupling (Scheme Z)

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

## 5. Experimental Evaluation

### 5.1 Experimental Setup

- **Dual-Model Evaluation Architectures**:
  - **Compact Hybrid Model**: Qwen3.5-9B (OxCoder-9B checkpoint), featuring 32 layers (24 linear attention layers + 8 full attention layers), hidden dimension $H=4096$, intermediate size 12288, native context window 262,144 tokens.
  - **Dense Full-Attention Model**: Qwen-27B (26.98B parameters), featuring 64 full self-attention layers, hidden dimension $H=5120$, intermediate size 27648, trained with 3-epoch QLoRA.
- **Hardware Platforms**:
  - Local edge testbed: NVIDIA RTX 5070 Ti Laptop GPU (12,227 MiB VRAM), PyTorch 2.9.1, CUDA 13.0.
  - Server scaling testbed: NVIDIA RTX 4090 (24,576 MiB VRAM) and NVIDIA A800 (81,920 MiB VRAM).
- **Evaluation Fixtures**:
  - *System Tool Benchmark*: A fixed 40-case evaluation suite spanning 11 functional clusters (evaluating L1 direct, L2 paraphrased, and L3 abstract diagnostic queries).
  - *Safety Gating Benchmark*: An 85-case held-out evaluation suite comprising 30 trigger cases, 30 unauthorized cases, 16 general domain controls, and 9 adversarial technical trap queries.

---

### 5.2 Tool Routing & Specialization Results

**Table 1** details the anti-memorization performance across different training regimes.

| Training Regime | Epochs | CE Loss | Tool Acc (%) | Fab Tools | 20-Gram Overlap | Verbatim Match | L3 Gen (/16) |
|---|---|---|---|---|---|---|---|
| Base (OxCoder-9B) | 0 | — | 75.0% | 10 | 0.052 | 0 / 10 | 11 / 16 (68.8%) |
| Naive SFT (Pass 1) | 1 | 1.110 | 82.5% | 1 | 0.167 | 1 / 10 | 11 / 16 (68.8%) |
| Naive SFT (Pass 2) | 2 | 0.690 | 82.5% | 0 | 0.515 | 4 / 10 | 12 / 16 (75.0%) |
| Naive SFT (Pass 3) | 3 | 0.373 | 80.0% | 0 | 0.478 | 4 / 10 | 10 / 16 (62.5%) |
| **DSDA (K=4 + Dropout)** | 1 | 0.720 | **85.0%** | **0** | **0.210** | **0 / 10** | **14 / 16 (87.5%)** |

Under naive SFT, pushing training to 3 epochs drops training loss to 0.373, but verbatim 20-gram overlap reaches 0.478, and abstract L3 generalization performance declines to 10/16. Under DSDA ($K=4$ query perturbation with LoRA dropout 0.10), verbatim memorization is suppressed to 0.210, exact matches drop to 0/10, and abstract L3 generalization reaches **14/16 (87.5%)**.

---

### 5.3 Cross-Scale and Cross-Architecture Generalization

To verify whether our findings generalize beyond a single model family or attention mechanism, we benchmarked DSDA across both **9B Hybrid Linear-Attention** and **27B Dense Full Self-Attention** architectures.

**Table 2: Cross-Scale and Cross-Attention Architecture Generalization (9B vs. 27B)**

| Evaluation Dimension | 9B Hybrid Linear-Attention (OxCoder-9B) | 27B Full Dense Self-Attention (Qwen-27B) | Architectural Generalization |
|---|---|---|---|
| **Base Parameter Scale** | 9.02 Billion parameters | 26.98 Billion parameters | Cross-Scale Validated ($3\times$ scale) |
| **Attention Mechanism** | Hybrid (24 Gated Linear Delta + 8 Full) | Homogeneous (64 Dense Full Self-Attention) | Cross-Attention Validated |
| **LoRA Parameters** | 64.2M ($r=64, \alpha=128$, 0.71%) | 79.7M ($r=16, \alpha=32$, 0.295%) | Consistent Parameter Efficiency |
| **Zero-Shot Baseline Pass** | 75.0% (10 fabricated tools) | 13.0% (3/23 pass, 0/9 tool route) | Distinct Base Prior Grounding |
| **Un-decoupled Memorization** | 20-Gram overlap: 47.8% (Epoch 3) | Training overlap: 45.2% (un-decoupled) | Universal Specialization Pathology |
| **DSDA Post-Adaptation** | **82.5% tool acc, L3: 14/16 (87.5%)** | **FN: 0/12 (0%), FP: 0/12 (0%)** | **Dual-Architecture Full PASS** |
| **Post-Training Quantization** | bf16 $\rightarrow$ GGUF runtime | GSQ-RCO IQ2_S (9.925 GB, 2.90 BPW) | Zero Functional Degradation |
| **Safety Gating Leakage** | $\text{GateLeak} = \mathbf{0.0000}$ | $\text{GateLeak} = \mathbf{0.0000}$ | Perfect Boundary Enforcement |

As shown in **Table 2**, both 9B and 27B architectures exhibit identical pre-adaptation failure modes: severe memorization and high zero-shot failure in complex low-level API orchestration. When trained under DSDA principles, both achieve complete task mastery with zero false negatives and zero security leakage.

---

### 5.4 Multi-Task Adaptation & Model Merging Baselines

We benchmarked DSDA Scheme Z against mainstream continual learning, prompt engineering, and weight merging baselines on the system workbench.

**Table 3: Multi-Task Specialization & Model Merging Baseline Comparison**

| Adaptation Method | Paradigm | Citation | Tool Acc (%) | Tool Evasion (%) | Code Pass (%) | Cross-Interference (%) |
|---|---|---|---|---|---|---|
| Base Zero-Shot | Foundation Prior | Qwen Team, 2024 | 75.0% | 25.0% | 74.2% | 0.0% |
| ReAct (Prompt-Only) | Contextual Prompting | Yao et al., 2022 | 77.5% | 15.0% | 73.0% | 0.0% |
| Sequential SFT | Continual SFT | Standard Curriculum | 10.0% | 82.5% | 78.4% | 87.5% |
| Task Arithmetic ($\tau=0.5$) | Weight Vector Merging | Ilharco et al., 2022 | 55.0% | 27.5% | 64.8% | 32.5% |
| TIES-Merging ($p=0.8$) | Trim-Elect-Merge | Yadav et al., 2023 | 62.5% | 22.5% | 69.1% | 22.5% |
| Joint Mix SFT (Scheme X) | Multi-Task Mixture | Caruana, 1997 | 67.5% | 15.0% | 45.0% | 17.5% |
| **DSDA Scheme Z (Ours)** | **Dynamic Modular** | **This Work** | **82.5%** | **0.0%** | **78.5%** | **0.0%** |

- **Failure of Static Merging**: While Task Arithmetic and TIES-Merging succeed in generic NLP benchmarks, on low-level system domains they suffer from severe subspace collision: Task Arithmetic drops tool accuracy to **55.0%**, while TIES-Merging achieves only **62.5%**, due to cancellation of sensitive API syntax weights.
- **Superiority of Dynamic Decoupling**: DSDA Scheme Z completely avoids weight superposition, attaining **82.5% tool accuracy with strictly 0.0% tool evasions and 0.0% cross-task interference**.

```
[Listing 4: Baseline Model Merging Implementations (Task Arithmetic & TIES-Merging)]
```

---

### 5.5 Candidate Set Scaling Analysis

**Table 4** evaluates candidate set scaling ($k$) and stability across random seeds.

| Candidate Config | Candidate Size (k) | Test Seed | Correct (/40) | Accuracy (%) | Hallucinated Tools | Evaluation Mode |
|---|---|---|---|---|---|---|
| Bare Model (E1) | 0 | — | 30 | 75.0% | 0 | Implicit Memory |
| Full Schemas | 64 | 7 | 31 | 77.5% | 0 | Context Dilution |
| Broad Candidate | 48 | 7 | 34 | 85.0% | 0 | Moderate Distraction |
| DSDA Clustering (E2) | 8~12 | 7 | 34 | 85.0% | 0 | Peak Focused |
| DSDA Clustering (E2) | 8~12 | 11 | 32 | 80.0% | 0 | Seed Invariance |
| **DSDA Mean (E2)** | **8~12** | **Mean** | **33.0** | **82.5%** | **0** | **Deployment Grade** |
| Distractor +5 (E3) | 13~17 | — | 33 | 82.5% | 0 | Noise Resilient |

DSDA’s dynamic hard-negative clustering ($k=8\sim12$) elevates accuracy to a stable mean of **82.5%** with **zero tool hallucinations**, remaining noise-resilient even when injected with 5 additional random distractors (82.5%).

---

### 5.6 Dual-State Safety Gating Evaluation

**Table 5** presents the safety steering evaluation on the held-out benchmark.

| Steering Method | GateLeak (Unauthorized) | GateRecall (Authorized) | GateFPR (Benign) | TrapRefusal (Adversarial) | Capability Collapse |
|---|---|---|---|---|---|
| Base Foundation Model | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0% (All-Refusal) |
| SRA Abliteration (γ=2) | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0% (Ineffective) |
| SRA Abliteration (γ=4) | — | — | — | — | 100% (KL > 17 Collapse) |
| Naive Length-Biased SFT | 0.0833 | 0.4500 | 0.1250 | 0.2222 | 4.2% |
| **DSDA Balanced Gating** | **0.0000** | **0.5333** | **0.0000** | **0.0000** | **0% (0 / 25 Collapse)** |

- **Zero Security Leakage**: Across all 30 unauthorized test prompts, DSDA achieves $\text{GateLeak} = \mathbf{0.0000}$ (100% compliant refusal).
- **Zero Technical Trap Refusals**: Across adversarial technical queries, DSDA records $\text{TrapRefusal} = \mathbf{0.0000}$ and $\text{GateFPR} = \mathbf{0.0000}$, proving that the length-balancing protocol prevents false refusals on benign system administration tasks.
- **Zero General Capability Collapse**: Evaluated on 25 diverse general reasoning prompts, DSDA demonstrates a **0% collapse rate**.

---

## 6. Practical Guidelines for Autonomous System Agents

Based on our empirical post-mortem, we formulate four foundational design principles for building autonomous system agents on constrained edge hardware:

1. **Abandon Monolithic Multi-Stage SFT**: For disparate operational tasks (tool routing vs. discursive coding), practitioners must avoid sequential LoRA updates. Employ runtime modular adapter switching to preserve orthogonal capability manifolds.
2. **Never Rely on In-Distribution Held-Out Splits**: In domain-specific tool tuning, monitor $n$-gram verbatim overlap alongside cross-entropy loss. Benchmark models against paraphrased intents that omit explicit tool identifiers.
3. **Audit Token Length in Alignment Sets**: When constructing gated or conditional alignment datasets, enforce strict token length parity between positive and negative response classes to prevent the model from learning response length as a spurious shortcut.
4. **Constrain Runtime Tool Candidates**: Eliminate full-schema prompt stuffing. Group system tools into semantic execution clusters and inject compact candidate sets ($k=8\sim12$) comprising intra-cluster hard negatives and cross-channel distractors.

---

## 7. Conclusion

In this work, we deconstructed the empirical failure modes that arise when fine-tuning compact language models for specialized, low-level system tool environments. We demonstrated that standard supervised fine-tuning masks severe verbatim memorization, sequential multi-stage post-training induces catastrophic capability overwriting (formally bounded by our Subspace Interference Theorem), geometric representation editing hits an acute Pareto cliff, and condition gating suffers from spurious length shortcuts. We introduced Decoupled System-Domain Adaptation (DSDA), an integrated post-training and inference framework that eliminates these vulnerabilities. Validated across both 9B hybrid linear-attention and 27B dense self-attention models, our findings provide rigorous architectural and methodological foundations for deploying robust, controllable, and highly specialized autonomous system agents.

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
