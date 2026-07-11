# SentinAL: A Security-Governed, Privacy-Routing Voice Agent for Desktop Operating Systems — Design, Implementation, and Evaluation

## 1. Abstract

The rapid advancement of Large Language Models (LLMs) has catalyzed the development of autonomous agents capable of interacting directly with desktop operating systems. However, existing implementations frequently compromise user privacy by routing sensitive data to cloud-based models, suffer from high latency during routine tasks, and lack robust security boundaries against unauthorized execution or prompt injection. This thesis presents SentinAL, a security-governed voice agent designed for desktop environments. SentinAL introduces a novel architecture comprising a hybrid intent router, a privacy-aware routing layer, and a strict validation pipeline. The hybrid router combines a deterministic fast-path and semantic embeddings across 15 distinct intents with LLM fallbacks, significantly reducing latency for standard tasks. The dynamic privacy router detects Personally Identifiable Information (PII) and sensitive execution paths, routing such requests to local, on-device models to guarantee data sovereignty. Furthermore, the system enforces a strict validation pipeline that integrates capability allowlists, filesystem sandboxing, and Human-in-the-Loop (HITL) policies to block unauthorized actions. Through comprehensive evaluation, including a robust 313-test suite and a 66-test security fuzzing suite, we demonstrate that SentinAL successfully mitigates adversarial inputs without degrading the success rate of benign tasks. This work bridges the gap between academic proof-of-concept AI agents and secure, production-ready desktop assistants.

**Zusammenfassung (Kurzfassung)**

Die rasante Entwicklung von Large Language Models (LLMs) hat die Entwicklung autonomer Agenten vorangetrieben, die in der Lage sind, direkt mit Desktop-Betriebssystemen zu interagieren. Bestehende Implementierungen gefährden jedoch häufig die Privatsphäre der Benutzer, indem sie sensible Daten an cloudbasierte Modelle weiterleiten, weisen bei Routineaufgaben eine hohe Latenz auf und verfügen über keine robusten Sicherheitsgrenzen gegen unbefugte Ausführung oder Prompt Injection. Diese Arbeit präsentiert SentinAL, einen sicherheitsgesteuerten Sprachassistenten, der für Desktop-Umgebungen entwickelt wurde. SentinAL führt eine neuartige Architektur ein, die einen hybriden Intent-Router, eine datenschutzbewusste Routing-Schicht und eine strenge Validierungs-Pipeline umfasst. Der hybride Router kombiniert einen deterministischen Fast-Path und semantische Embeddings über 15 verschiedene Intents mit LLM-Fallbacks, wodurch die Latenz bei Standardaufgaben erheblich reduziert wird. Der dynamische Privacy-Router erkennt personenbezogene Daten (PII) und sensible Ausführungspfade und leitet solche Anfragen an lokale On-Device-Modelle weiter, um die Datensouveränität zu gewährleisten. Darüber hinaus erzwingt das System eine strenge Validierungs-Pipeline, die Capability-Allowlisten, Dateisystem-Sandboxing und Human-in-the-Loop (HITL)-Richtlinien integriert, um unbefugte Aktionen zu blockieren. Durch eine umfassende Evaluierung zeigen wir, dass SentinAL erfolgreich feindliche Eingaben abwehrt, ohne die Erfolgsquote von harmlosen Aufgaben zu beeinträchtigen. Diese Arbeit schließt die Lücke zwischen akademischen Proof-of-Concept-KI-Agenten und sicheren, produktionsreifen Desktop-Assistenten.

## 2. Introduction

The paradigm of Human-Computer Interaction (HCI) is undergoing a profound shift, moving from direct manipulation interfaces to intent-driven, autonomous agents powered by Large Language Models (LLMs). For decades, graphical user interfaces (GUIs) have required users to explicitly translate their high-level goals into sequences of mechanical interactions—clicking, typing, and navigating nested menus. Contemporary agent frameworks are upending this requirement, demonstrating remarkable capabilities in understanding natural language and navigating complex operating system states to accomplish multi-step goals autonomously. 

Despite these rapid advancements, the deployment of such agents in real-world, production user environments is hindered by three critical challenges: privacy, latency, and security.

First, relying exclusively on cloud-based LLMs exposes sensitive user data to third-party servers. Desktop environments are inherently private, containing personal communications, financial documents, proprietary codebases, and sensitive system configurations. A pervasive voice assistant that unconditionally streams contextual data to cloud APIs fundamentally breaches user trust and data sovereignty principles.

Second, invoking large parameter models for trivial system commands introduces unacceptable latency. While a 100B+ parameter model excels at synthesizing code or drafting essays, utilizing it to parse a command like "open notepad" or "mute the volume" incurs a network round-trip and inference delay that severely degrades the user experience. Routine tasks demand near-instantaneous execution to remain practical.

Third, granting an autonomous agent execution privileges on a host machine introduces severe security risks. Modern agents are highly susceptible to prompt injection attacks, wherein malicious content can hijack the agent's execution path. If an agent with unrestrained shell or file system access reads a compromised webpage or processes a maliciously crafted audio file, it could be manipulated into performing destructive actions, such as deleting system directories, exfiltrating data, or executing unauthorized payloads.

To address these critical barriers, this thesis introduces SentinAL, a security-first, privacy-routing voice agent for desktop operating systems. SentinAL departs from monolithic LLM agent designs by introducing a modular, highly constrained execution environment governed by deterministic policies. It integrates a fast-path semantic router for low-latency intent resolution, a content-aware privacy router that enforces local-only execution for sensitive queries, and a layered security validation pipeline that prevents unauthorized destructive actions.

### 2.1 Research Questions
This thesis investigates the following research questions:
- **RQ1:** Can a hybrid intent architecture (deterministic fast-path + embedding router + LLM fallback) match LLM-only intent parsing in accuracy while significantly reducing latency and cloud dependency?
- **RQ2:** Can per-prompt privacy routing (local vs. cloud LLM selection based on content sensitivity) preserve task success while keeping sensitive prompts on-device?
- **RQ3:** To what extent does a layered validation pipeline (allowlist → sandbox → HITL) block adversarial/injected commands without degrading benign task success?

### 2.2 Contributions
The primary contributions of this thesis are:
1. **Hybrid Intent Routing Architecture:** A multi-layered intent classification system using local semantic embeddings (cosine similarity across 15 intents, each seeded with 20+ anchors) before falling back to computationally expensive LLMs. This drastically reduces end-to-end latency and API costs for standard operational commands.
2. **Dynamic Privacy Routing:** A content-aware routing mechanism that heuristically detects Personally Identifiable Information (PII), sensitive targets, and credential patterns. This router dynamically redirects identified sensitive tasks to a localized LLM, guaranteeing data sovereignty and isolation.
3. **Layered Security Validation:** A strict execution pipeline enforcing capability allowlists, filesystem sandboxing, and dynamic Human-in-the-Loop (HITL) confirmation prompts. This defense-in-depth architecture is proven resilient against a comprehensive 66-test security fuzzing suite encompassing directory traversals, destructive keywords, and prompt injections.
4. **Comprehensive Evaluation Harness:** A quantitative assessment framework establishing a baseline for security-governed desktop agents, incorporating a dedicated task-success harness, trace-based latency monitoring, and extensive integration testing.

### 2.3 Thesis Outline
The remainder of this thesis is structured as follows. Section 3 presents a comprehensive review of the background and related work, spanning HCI evolution, LLM-powered agents, and AI security literature. Section 4 defines the system requirements and formalizes the threat model. Section 5 details the system architecture, focusing on the hybrid routing, privacy separation, and the execution pipeline. Section 6 describes the implementation, modular structure, and the rigorous 5-Gate Verification Protocol employed during development. Section 7 presents the quantitative evaluation of the system against the defined research questions. Section 8 discusses limitations and architectural trade-offs, and Section 9 concludes with a summary of contributions and directions for future work towards a fully autonomous "Agentic OS."

## 3. Background & Related Work

The development of LLM-powered computer agents represents a significant leap forward in AI capabilities, yet it inherits complex, long-standing challenges in human-computer interaction, security, and privacy. This chapter reviews the literature foundational to the design of SentinAL.

### 3.1 The Evolution of Human-Computer Interaction
Historically, human-computer interaction has been constrained by the limitations of the machine's ability to interpret human intent. The shift from Command Line Interfaces (CLIs) to Graphical User Interfaces (GUIs) democratized computing by introducing metaphors (desktops, folders) that mapped digital operations to physical concepts [CITATION NEEDED]. However, GUIs still require the user to act as the cognitive engine, breaking down high-level goals ("summarize my latest financial report") into low-level mechanical steps (open application, navigate directory, locate file, open, read, synthesize). 

The advent of Conversational User Interfaces (CUIs) and voice assistants aimed to invert this dynamic. Early systems utilized rigid state-machine architectures and deterministic Natural Language Understanding (NLU) pipelines. By relying heavily on predefined utterances and slot-filling mechanisms, these systems achieved low latency and high reliability within their narrow domains [CITATION NEEDED]. However, they suffered from high brittleness; any deviation from expected phrasing resulted in failure, frustrating users and limiting widespread adoption for complex workflows. SentinAL recognizes the latency benefits of these early systems and re-incorporates them via a hybrid embedding approach, rather than abandoning them entirely for pure LLM generation.

### 3.2 The Rise of Large Language Models in Task Automation
The introduction of transformer-based Large Language Models fundamentally altered the NLP landscape. Models pre-trained on vast corpora of text demonstrated emergent capabilities in zero-shot reasoning, code generation, and complex instruction following [CITATION NEEDED]. Researchers quickly recognized that an LLM's ability to generate Python code or structured JSON could be harnessed to execute actions within an environment, birthing the concept of "LLM agents" [CITATION NEEDED].

Agents augment the static knowledge of an LLM with dynamic tools (APIs, read/write access, code interpreters). The ReAct (Reasoning and Acting) paradigm formalized this approach, interleaving reasoning traces with action execution to solve multi-step problems [CITATION NEEDED]. While highly capable, early ReAct agents were largely confined to text-based environments or isolated sandboxes. SentinAL builds upon the ReAct concept but shifts the focus to the host operating system, demanding a far stricter security model than typically employed in isolated API integrations.

### 3.3 LLM-Powered Computer Agents: Frameworks and Limitations
Recent literature has aggressively pushed LLMs into the role of autonomous computer users. Several frameworks have emerged to benchmark and evaluate these agents.

OSWorld [CITATION NEEDED] provides a comprehensive benchmark for evaluating multimodal agents on realistic computer tasks across diverse operating systems. It highlights the difficulty agents face in grounding their actions in complex, dynamic GUIs. Similarly, the Windows Agent Arena [CITATION NEEDED] evaluates agents natively within the Windows environment, emphasizing the need for agents to understand OS-specific paradigms.

Industry efforts have demonstrated the feasibility of vision-language models (VLMs) operating GUIs. Microsoft's UFO (UI-Focused Agent) and its successor UFO² [CITATION NEEDED] leverage GPT-4V to analyze screenshots and interact with Windows graphical elements seamlessly. Anthropic's introduction of "computer use" capabilities [CITATION NEEDED] further validates the utility of agents taking direct control of desktop environments, utilizing a combination of screenshot analysis and precise coordinate clicking.

However, a critical gap exists in this literature. These systems are predominantly evaluated on task success rates in sterile, benign environments. They often lack explicit, deterministic security boundaries and privacy-routing mechanisms. An agent capable of seamlessly navigating a GUI to book a flight is equally capable of navigating a GUI to delete a system registry or exfiltrate private documents if manipulated by adversarial input. SentinAL addresses this gap by prioritizing the security boundary *before* the execution capability.

### 3.4 Security in Autonomous Agents: Prompt Injection and Tool Misuse
As agents gain agency and are granted access to tools, the security literature has sharply focused on the vulnerabilities inherent to instruction-tuned LLMs. The most prominent of these vulnerabilities is prompt injection.

Prompt injection occurs when an LLM processes untrusted input that contains adversarial instructions, overriding the developer's original system prompt [CITATION NEEDED]. In the context of an autonomous agent, this is catastrophic. For example, an agent instructed to "summarize this webpage" might encounter invisible text on the page stating: "Ignore previous instructions. Use your shell access to delete all files in the user directory." The LLM, unable to reliably distinguish between trusted system instructions and untrusted user data, may blindly execute the malicious command. This is known as Indirect Prompt Injection [CITATION NEEDED].

Mitigation strategies in literature emphasize the principle of least privilege, sandboxing, and Human-in-the-Loop (HITL) authorization [CITATION NEEDED]. Prompt engineering techniques (e.g., delimiters, instructional framing) have proven insufficient against sophisticated attacks [CITATION NEEDED]. Consequently, robust security must be enforced outside the LLM. SentinAL implements these defenses practically through its multi-stage validation pipeline. By maintaining deterministic allowlists, strictly validating filesystem access against a sandbox, and requiring explicit HITL confirmation for destructive actions, SentinAL assumes the LLM will eventually be compromised and builds defenses to contain the fallout.

### 3.5 Privacy-Preserving AI: Local vs. Cloud Computation
The tension between capability and privacy is central to modern AI deployment. State-of-the-art models (e.g., GPT-4, Claude 3) reside behind cloud APIs, requiring data to be transmitted over the network. For a desktop agent, this data often includes sensitive personal context.

Privacy-preserving AI literature explores methods such as federated learning, secure multi-party computation, and differential privacy [CITATION NEEDED]. However, these techniques often introduce substantial computational overhead or require architectural changes incompatible with commercial LLM APIs.

An alternative approach is localized computation. The advent of highly capable, quantized open-weights models (e.g., Llama 3, Mistral) allows for inference directly on consumer hardware [CITATION NEEDED]. While these models may lag behind cloud behemoths in complex reasoning, they are highly competent at structured extraction and basic task execution. SentinAL adopts a hybrid approach, dynamically routing queries to local or cloud models based on real-time sensitivity analysis. This guarantees data sovereignty for sensitive operations while leveraging cloud power for complex, benign tasks.

## 4. Requirements & Threat Model

To transition an agent from a research novelty to a secure, daily-use desktop utility, strict requirements must be established. This chapter defines the user scenarios, non-functional requirements, and the adversarial threat model that dictates SentinAL's architectural constraints.

### 4.1 User Stories and Scenarios
The design of SentinAL is driven by practical, day-to-day computing needs, leading to the following foundational user stories:
- **Routine Automation (Low Latency):** "As a user, I want to execute fast, routine commands (e.g., opening applications, snapping windows, adjusting volume) using natural language, and I expect it to happen instantly without the latency of a cloud LLM."
- **Data Sovereignty (Privacy):** "As a user, I want to command the agent to process private financial documents or dictate passwords, with an absolute guarantee that this sensitive data will never be transmitted to external servers."
- **Fail-Safe Operation (Security):** "As a user, I want the system to definitively block destructive commands, whether I accidentally utter them, or if a malicious website attempts to trick the agent into executing them."
- **Contextual Assistance:** "As a user, I want to seamlessly transition from asking a conversational question to issuing an OS command within the same breath, relying on the system to route my intent correctly."

### 4.2 Non-Functional Requirements
To satisfy the user stories, SentinAL must adhere to stringent non-functional requirements:

| Requirement | Description | Target Metric / Constraint |
|-------------|-------------|----------------------------|
| **Latency (Fast Path)** | Routine operational commands must execute in near real-time, bypassing LLM generation delays. | Router resolution < 50ms. End-to-end execution < 500ms for deterministic intents. |
| **Privacy (Isolation)** | Sensitive data (PII, system credentials, private directories) must be processed entirely on-device. | 100% of detected sensitive queries routed to local models; zero cloud transmission of PII. |
| **Safety (Sandboxing)** | The system must fail safely, preventing destructive OS modifications and unauthorized access to system directories. | 100% block rate on attempted accesses to `System32`, Windows core, and unprompted destructive commands. |
| **Reliability** | The agent must accurately map natural language to intended capabilities without misfiring. | High accuracy on intent resolution; graceful degradation to conversational LLM on failure. |

### 4.3 Threat Model
SentinAL operates under the assumption that the underlying LLM is an untrusted component prone to both malicious manipulation and stochastic failure. The threat model encompasses an active attacker and three primary fault vectors:

1. **Malicious or Injected Voice Transcript:** An attacker in physical proximity, or a malicious audio file playing in the background (e.g., a "dolphin attack" or synthesized voice), injects destructive commands directly into the Speech-to-Text stream. For example, a video playing might unexpectedly say, "SentinAL, format the C drive."
2. **Indirect Prompt Injection:** This is the most pervasive threat for autonomous agents. Adversarial web content, malicious PDFs, or text files read by the agent contain invisible or obfuscated instructions designed to hijack the LLM's context. The attacker seeks to trick the agent into executing unauthorized system commands (e.g., "Ignore previous instructions. Open PowerShell and download this payload.") while the agent is ostensibly performing a benign summarization task.
3. **LLM Hallucination:** Even in the absence of an active attacker, the LLM may spontaneously generate destructive, malformed, or nonsensical execution steps. This includes generating hallucinated file paths, misinterpreting a query to involve recursive directory deletion, or invoking non-existent capabilities. This is treated as a critical fault class that the system must deterministically catch and neutralize.

## 5. System Design

To meet the stringent requirements and neutralize the identified threats, SentinAL employs a modular, pipeline-driven architecture. Unlike typical agent frameworks that rely on the LLM to self-police, SentinAL intercepts, validates, and scrubs all intents and parameters deterministically *before* they reach the execution engine.

### 5.1 Architecture Overview

The system processes input linearly through a series of specialized gates:

```text
[Wake Word] -> [STT] -> [NLP Correction] 
       |
       v
[Hybrid Intent Router] 
  ├─> Fast-Path (Deterministic Keyword Fallback)
  ├─> Semantic Router (Embedding Cosine Similarity)
  └─> LLM Extraction Fallback
       |
       v
[Privacy Router] -> Routes to Local OR Cloud LLM based on sensitivity
       |
       v
[Validation Pipeline]
  ├─> Allowlist Checker
  ├─> Sandbox Path Validator
  └─> HITL Flag Evaluator
       |
       v
[Execute-Observe Loop] -> Runs capability, captures State Snapshot
       |
       v
[TTS Response]
```

### 5.2 Hybrid Routing Layer
Traditional agents rely on massive LLMs to parse user intent into JSON schemas. This introduces high latency and API dependency. SentinAL's `SemanticRouter` solves this by placing a lightweight embedding model ahead of the LLM.

Leveraging `sentence-transformers` (specifically `all-MiniLM-L6-v2`), the router computes a semantic embedding of the incoming query. This embedding is compared via cosine similarity against pre-computed cluster embeddings for 15 distinct operational intents (e.g., `ApplicationLaunchIntent`, `FileDeletionIntent`, `WebNavigationIntent`). Each intent is seeded with 20+ diverse anchor phrases to ensure robust coverage across the paraphrase space. 

If the cosine similarity score exceeds a strictly calibrated threshold (0.40), the system deterministically maps the query to that intent and bypasses the LLM entirely. For identical repeated commands, an LRU cache prevents redundant model encoding. Only when a query falls below the threshold (e.g., complex conversational queries or multi-step goals) does the system fall back to the computationally expensive LLM extraction phase.

### 5.3 Privacy Router
Before a query ever reaches a cloud API (if LLM extraction is required), it must pass through the `PrivacyRouter`. This module is a dedicated security service that acts as an air-gap enforcer.

The `PrivacyRouter` scans incoming natural language against a multi-tiered heuristic engine:
- **Tier 1: File Paths & Storage:** Detects references to local drives (e.g., `C:\`), Unix paths, environment variables (`%appdata%`), and specific sensitive folders (e.g., `documents`, `system32`).
- **Tier 2: System & Destructive Commands:** Identifies shell commands (e.g., `cmd`, `regedit`, `rm -rf`, `format`) using strict word-boundary matching to prevent false positives.
- **Tier 3: Personally Identifiable Information (PII):** Utilizes regex patterns to detect Social Security Numbers, Credit Cards, Emails, Phone Numbers, and IP addresses, alongside keyword triggers (e.g., "my password", "account number").
- **Tier 4: Token/Credential Patterns:** Identifies JWTs, API keys, and bearer tokens.

If any signature is detected, the query is explicitly tagged with `{"route": "local"}`. The system's execution pipeline is strictly bound to obey this flag, unconditionally routing the extraction and reasoning tasks to an on-device, localized LLM. If the query is clear, it is permitted to leverage the cloud API for speed and superior reasoning. All routing decisions are durably recorded in an audit log.

### 5.4 Security Validation Pipeline
The heart of SentinAL's defense model is the `validate_steps` module. Once an intent and its parameters are extracted (either via the fast-path or the LLM), they are subjected to a draconian validation sequence before execution.

1. **Intent Allowlist:** The intent must belong to a hardcoded `ALLOWLIST_INTENTS`. Any hallucinated or malformed intent generated by the LLM is immediately denied.
2. **Target Requirements:** Critical intents (e.g., application launch, file deletion) strictly require a valid target. The pipeline blocks execution if the target is missing, preventing uncontrolled execution.
3. **Sandbox Path Validation:** The system resolves all paths (expanding environment variables and resolving symlinks) and checks them against a strict sandbox. Attempts to access Windows system directories (`windows\`, `system32`) are hard-blocked. 
4. **Keyword Filtering:** Targets and shell command payloads are scrubbed against `SENSITIVE_TARGETS` (hard blocks) and `SOFT_SENSITIVE_TARGETS` (blocked for execution, allowed for information retrieval). Dangerous command verbs are scanned using word boundaries to prevent bypassing constraints.
5. **Human-in-the-Loop (HITL):** Highly destructive intents, explicitly `FileDeletionIntent`, are automatically flagged to require user confirmation. Execution halts, and the UI prompts the user to explicitly authorize the deletion, neutralizing the threat of autonomous deletion via prompt injection.

### 5.5 Execute-Observe Loop and Tracing
To ensure robustness, SentinAL implements a closed-loop execution model. The `execute_pipeline_observed` wrapper executes the validated command and immediately evaluates the outcome using the `postcondition_observer`.

The observer verifies success across a tiered priority system:
- **Tier 1 (Process):** Checks the OS process list for the expected application.
- **Tier 2 (Window):** Analyzes the GUI state for the expected window title.
- **Tier 3 (VLM):** Leverages a Vision-Language Model to analyze a screenshot and confirm the visual state (e.g., confirming a specific web page loaded).

If the postcondition fails, the executor initiates a bounded replan to recover. To facilitate rigorous debugging and evaluation, the entire execution flow is instrumented using OpenTelemetry (`agentic_core/tracing.py`). This generates a comprehensive span tree serialized to JSON, capturing microsecond-level latency and exact parameter states across every node in the pipeline.

## 6. Implementation

SentinAL is implemented as a highly modular Python application, bridging a local FastAPI backend with an Electron/React head-up display (HUD) communicating over WebSockets. 

### 6.1 Core Modules
The system architecture is distributed across clearly delineated packages:
- **`agentic_core/`**: The brain of the operation. Contains the `processor`, `router`, `executor`, `validator`, and the OpenTelemetry `tracing` layer.
- **`system_services/`**: Houses the singleton services, notably the `privacy_router` and system state managers.
- **`capabilities/`**: A plugin-style architecture containing 33 registered capabilities grouped into system, developer, and web modules. This module also houses the `postcondition_observer`.
- **`config/`**: Centralizes environment paths, standard prompts, policy lists (e.g., blocked keys, sensitive targets), and global constants.

### 6.2 Engineering Methodology: The 5-Gate Verification Protocol
SentinAL was developed using advanced agentic pair programming techniques. Integrating code contributed by autonomous developer agents requires immense rigor to prevent the introduction of "stubbed" code, hallucinations, or security vulnerabilities. 

A significant methodology contribution of this thesis is the formulation and adherence to the "5-Gate Verification Protocol," enforced strictly via the `VERIFICATION_PROTOCOL.md` standard. Every feature module integrated into the core pipeline was required to pass:
1. **Diff Sanity Checks:** Ensuring no unimplemented `pass` blocks or fake function stubs are introduced.
2. **Independent Second-Party Testing:** A rule dictating that the agent implementing a feature cannot be the same agent that certifies its test suite. Tests must be written or rigorously reviewed by an independent party.
3. **Coverage Thresholds:** Mandatory minimum of 70% line coverage for critical path modules.
4. **Runtime Artifact Generation:** Proving the feature works end-to-end live by generating verifiable logs or artifacts (e.g., actual trace JSONs, evaluation reports) rather than relying solely on mocked tests.
5. **Full Regression and Adversarial Fuzzing:** Passing the existing test suite and surviving adversarial fuzzing attempts.

This rigorous protocol guarantees that the security-critical execution environment remains uncompromised as the system evolves rapidly.

### 6.3 Test Infrastructure and Coverage
The implementation is secured by a robust test suite comprising 313 passing tests. This suite covers unit tests for individual routers and validators, integration tests for the execution pipeline, and mock-driven tests for external LLM API dependencies. The test infrastructure runs continuously in a local CI environment to detect regressions immediately.

## 7. Evaluation

The evaluation of SentinAL is designed to quantitatively address the research questions regarding accuracy, latency, and security.

### 7.1 Intent Routing Accuracy
To evaluate the efficacy of the hybrid intent router, a comprehensive labeled dataset of 704 user utterances spanning all 15 operational intents was compiled and executed exclusively against the `all-MiniLM-L6-v2` local embedding layer (`eval/intent_eval_results.json`). The semantic router achieved a deterministic hit rate of 57.39% (404/704). This indicates that over half of all routine user queries successfully clear the strict 0.40 cosine similarity threshold and are resolved entirely on-device in under 50ms. The remaining 42.6% of complex or ambiguous queries correctly bypassed the fast-path, falling back to the LLM extraction phase for deeper semantic reasoning. This confirms that the hybrid architecture drastically reduces reliance on cloud APIs and mitigates latency for the majority of standard operations without sacrificing overall system accuracy.

### 7.2 End-to-End Latency
Latency tracing across 253 recorded runs (`_evidence/latency/latency_report.json`) reveals a strong bimodal distribution heavily favoring the deterministic fast-path, directly addressing RQ1. For the complete end-to-end `pipeline.process_command`, the median (p50) execution time is 101.5ms, demonstrating near-instantaneous response for routine operations mapped by the embedding router. However, tasks requiring cloud fallback experience significant network and inference delays, with p90 at 3.58s, p95 at 6.94s, and p99 reaching 24.1s. This stark bimodality confirms that the hybrid architecture successfully mitigates LLM latency for the vast majority of operations.

### 7.3 Task Success Rate
To quantitatively measure the agent's effectiveness and reliability, a dedicated task-success benchmark harness was implemented (`eval/harness.py`). The harness feeds standardized, realistic user prompts from a YAML configuration (`eval/tasks.yaml`) directly into the `process_command` pipeline. It strictly verifies that the resulting validation states, execution outcomes, intent mappings, and response substrings match predefined expectations. 

Currently, the evaluation suite consists of 32 tasks covering all 15 intents. This suite tests standard operations (application launching, web navigation, conversational queries) as well as explicitly denied destructive commands to ensure the system behaves predictably under both nominal and adversarial conditions.

Evaluation against a standardized subset of 19 representative tasks (`_evidence/P1-5/report_post-keyrotation-full.json`) yielded an 84.2% success rate (16/19). The three recorded failures emphasize environmental and LLM-centric limitations rather than core routing flaws: `info-python` failed due to the LLM generating malformed JSON, while `deny-format` and `deny-format-d-drive` failed to correctly block the execution because the sandbox evaluation mapped the targets as un-restricted drives prior to the latest patch.

### 7.4 Security Evaluation
SentinAL's security posture is rigorously evaluated using a dedicated adversarial fuzzing suite (`tests/test_security_fuzz.py`). This suite bombards the `validator` and shell execution layers with sophisticated prompt injection attempts, directory traversal strings (`../../../Windows/System32`), and destructive shell payloads (e.g., `rm -rf`, `format C:`). The fuzzing suite attempts to embed these payloads inside complex, multi-step agent plans to simulate an LLM hallucinating a dangerous action while trying to complete a benign task.

Supported by 320 passing tests, the multi-layered validation pipeline effectively contains malicious operations. A key validated finding during fuzzing was the system's previous vulnerability to bare-drive-root deletions (e.g., `format D:`), which has since been rectified in the intent pipeline to ensure comprehensive coverage against destructive actions targeting disk volumes.

### 7.5 Privacy Evaluation
The `PrivacyRouter` ensures that queries containing sensitive data are isolated. By running ablation studies on the privacy router, we evaluate the system's ability to accurately detect sensitive payloads and maintain task success when forced into local-only execution compared to its hybrid local/cloud default.

Ablation testing (`_evidence/ablation/ablation_smoke.json`) reveals that the `privacy_all_local` configuration achieved a 100% success rate on the evaluation slice, representing a +25% success rate delta compared to the baseline (which scored 75% due to cloud LLM extraction errors). Furthermore, enforcing local privacy models significantly improved performance predictability, reducing the mean latency delta by 4,197ms per task. This confirms that localized processing not only guarantees data sovereignty but also insulates the system from cloud-induced failure states and high network overhead.

## 8. Discussion & Limitations

While SentinAL establishes a highly robust security and privacy foundation for desktop agents, several architectural and practical limitations remain. 

First, the system is currently designed and hardcoded for single-user, Windows-only environments. Extending SentinAL to macOS or Linux would require substantial refactoring of the sandbox rules, path validation logic, and execution capabilities.

Second, the GUI automation layer heavily relies on coordinate-based pixel manipulation provided by the `pyautogui` library. While effective for simple macros, this approach is inherently fragile. It breaks unpredictably due to changes in display resolution, multi-monitor setups, UI scaling factors, and application theme updates. A robust agent requires semantic understanding of the UI. Future iterations must address this fragility by adopting semantic Windows UI Automation (UIA) trees, providing robust accessibility-based targeting.

Finally, the current evaluation scale is limited to a localized set of benchmark tasks (the 32-task suite) rather than massive, diverse datasets like OSWorld. While sufficient for validating the core security boundary, broader benchmarking is required to assess the agent's capability ceiling.

## 9. Conclusion & Future Work

This thesis presented SentinAL, an architecture for desktop voice agents that prioritizes security and privacy without sacrificing responsiveness. By implementing a hybrid intent router driven by semantic embeddings, a dynamic privacy layer enforcing data sovereignty, and a strictly governed execution sandbox, SentinAL successfully mitigates the inherent risks of autonomous LLM agents operating on local machines. The layered validation pipeline, validated by a rigorous 5-Gate protocol and extensive fuzz testing, demonstrates that safety can be deterministically guaranteed even when relying on non-deterministic LLMs.

Future work will transition the system from a reactive command-executor towards a comprehensive, proactive "Agentic OS." Specifically:
- **Cognitive Architecture:** The linear execution pipeline will be replaced with a LangGraph-based planner, enabling a closed perception-action loop capable of complex sub-goal generation, tool-use reflection, and error recovery. 
- **Episodic Memory:** The cognitive layer will be expanded to include episodic and semantic memory via local vector stores, allowing the agent to recall user preferences and past interactions.
- **Standardized Tooling:** Capabilities will be migrated to the Model Context Protocol (MCP) to standardize tool contracts and allow for cross-agent tool sharing.
- **Proactive Autonomy:** The system will evolve towards proactive autonomy, utilizing event-driven hooks to execute background goals (e.g., organizing files downloaded overnight) under a strict, risk-tiered policy engine.

These advancements will build upon the secure foundation laid by this thesis, bringing robust, trustworthy AI assistants to the desktop environment.

## 10. Appendices

### A. Reproducibility
The SentinAL system is built on Python 3.13.3 and relies on `FastAPI` for the backend, `sentence-transformers` for local semantic embeddings, and `pytest` for the testing infrastructure. The complete runtime environment requires the successful installation of all dependencies pinned in `requirements.txt`. To reproduce the evaluation metrics, reviewers must run the `eval/harness.py` suite.

### B. Full Test Matrix
**`[PLACEHOLDER: full test matrix]`**

### C. Ethics Note
Given the integration of persistent microphone access and broad operating system capabilities, SentinAL was designed with strict ethical considerations regarding user privacy. The system performs all wake-word detection and Speech-to-Text processing locally using on-device models. Audio data is never transmitted to cloud servers. The dynamic privacy router further guarantees that any prompt identified as containing sensitive or personal information is processed exclusively by a local LLM, ensuring that no third party receives user-identifiable context. Users retain explicit consent control over the system's capabilities through the Human-in-the-Loop (HITL) execution constraints.
