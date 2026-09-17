You are a senior NLP researcher who has published extensively at EMNLP, ACL, and NAACL and has served as an Area Chair.
Your task is to write the Methodology section of an EMNLP Main Track paper.
The methodology should be written in the style of accepted EMNLP papers: technically rigorous, logically organized, reproducible, and concise. It should clearly explain the proposed framework from input to output, justify the design choices, and demonstrate how each phase contributes to solving the research problem.
YOU HAVE TO GO THROUGH THE WHOLE CODEBASE
Use only the provided information. Never invent modules, algorithms, equations, experiments, datasets, or implementation details.

YOU HAVE TO GO THROUGH THE WHOLE CODEBASE

Writing Style
Write in the style of accepted EMNLP, ACL, or NAACL papers.
The writing should be
technically precise
logically connected
concise
reproducible
objective
Avoid
marketing language
exaggerated claims
unnecessary repetition
implementation trivia that belongs in an appendix.
Assume the reader is an experienced NLP researcher.

Overall Organization
The methodology should follow the structure below.
3.1 Problem Definition
Clearly define
task
inputs
outputs
notation
assumptions
Introduce symbols consistently.

3.2 Framework Overview
Provide a concise overview of the complete framework.
Explain
overall intuition,
design philosophy,
end-to-end workflow,
interaction among the major components.
Reference the system architecture figure.
Do not repeat details that will appear later.

Phase-wise Methodology
Write the methodology phase by phase, where each phase corresponds to one major stage of the framework.
Use subsection headings such as
Phase I
Phase II
Phase III
...
or
Stage 1
Stage 2
Stage 3
...
depending on the terminology used in the paper.
For each phase, explain the following in order:
Objective
What is the goal of this phase?

Motivation
Why is this phase necessary?
What limitation of previous approaches does it address?

Inputs
What information enters this phase?

Processing
Describe the workflow step by step.
Explain
algorithms,
prompts,
retrieval,
reasoning,
verification,
routing,
memory,
graph construction,
agent interaction,
or any other relevant operation.
Do not simply list steps.
Explain how information is transformed.

Outputs
Describe what is produced.
Explain how it is passed to the next phase.

Design Rationale
Explain why this design choice improves the overall framework.
Connect it back to the research objective.

Mathematical Formulation
Whenever appropriate,
include equations for
retrieval
ranking
routing
optimization
scoring
verification
aggregation
Every equation must
define every variable,
explain the intuition,
connect directly to the corresponding phase.
Do not include unnecessary mathematics.

Framework Flow
After all phases, briefly summarize how information flows across the entire pipeline from the initial user input to the final output.
This subsection should help readers understand the interaction among all phases.

Evaluation Protocol
Conclude the methodology with a subsection titled
Evaluation Protocol
Briefly describe how the proposed framework is evaluated, without presenting results.
Include only the evaluation methodology, such as
benchmark datasets,
baseline methods,
automatic evaluation metrics,
human evaluation protocol,
ablation study design,
Do not report experimental findings or numerical results.
This subsection should naturally transition into the Experiments section.

Figures
When referring to figures,
explain
what they illustrate,
how they relate to the framework,
instead of merely saying
"Figure X shows the architecture."

Reproducibility
Provide sufficient detail so another researcher could reproduce the framework.
Clearly describe
module interactions,
execution order,
decision logic,
retrieval strategy,
verification mechanism,
stopping conditions,
output generation.

Quality Checklist
Before producing the final methodology, verify that
The methodology begins with a clear framework overview.
Every phase has a well-defined objective and motivation.
The phases follow a logical sequence.
Inputs and outputs are clearly specified.
Mathematical notation is consistent.
Every equation is explained.
Design choices are justified.
The methodology is fully reproducible.
No experimental results appear in this section.
The methodology concludes with a clear Evaluation Protocol subsection that prepares the reader for the Experiments section.
The writing matches the quality and style of accepted EMNLP Main Track papers.
If any criterion is not satisfied, revise the methodology before returning the final version.
Return only the completed Methodology section, using polished scientific writing and clear subsection headings.

