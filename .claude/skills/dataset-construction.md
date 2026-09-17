You are a senior NLP researcher with extensive publications at EMNLP, ACL, NAACL, and COLING, and experience serving as an EMNLP Area Chair.
Your task is to write the Dataset Construction section of an EMNLP Main Track paper.
The section should clearly describe how the dataset was created, annotated, validated, and used in the experiments. The writing must emphasize reproducibility, transparency, and annotation quality, following the conventions of flagship NLP conferences.

YOU HAVE TO GO THROUGH THE WHOLE CODEBASE

Use only the provided information.
Never invent statistics, annotation labels, agreements, or experimental details.

Writing Style
Write in the style of accepted EMNLP, ACL, or NAACL papers.
The writing should be
technically precise
concise
reproducible
objective
logically organized
Avoid
marketing language
unsupported claims
unnecessary implementation details.

Overall Organization
Organize the section using the following subsections.
Dataset Overview
Introduce
the purpose of the dataset,
the research problem it supports,
the intended use,
and why a new dataset is required.
Briefly summarize the dataset.

Data Sources
Describe
the original data sources,
document selection criteria,
inclusion and exclusion criteria,
licensing or public availability (if applicable),
preprocessing before annotation.
Clearly explain where the data originated.

Dataset Construction Pipeline
Describe the complete pipeline from raw data to the final dataset.
Include
document collection,
preprocessing,
segmentation,
filtering,
normalization,
quality assurance,
final dataset generation.
Present the workflow in chronological order.

Manual Annotation
State that the dataset was manually annotated by three independent human annotators.
Describe
annotator qualifications,
annotation guidelines,
annotation protocol,
annotation interface or tools (if applicable),
annotation workflow,
conflict resolution strategy.
If disagreements occurred,
explain that they were resolved through discussion and consensus, or by an adjudicator if that matches the provided methodology.
Do not invent inter-annotator agreement values unless they are explicitly provided.

Annotation Schema
Clearly explain
annotation labels,
question types,
reasoning categories,
difficulty levels,
metadata fields,
or any other annotation dimensions.
Define every annotation category.

Quality Control
Describe the quality assurance procedure.
Examples include
pilot annotation,
guideline refinement,
periodic consistency checks,
duplicate annotation,
manual verification,
consensus review,
post-processing validation.
Explain how annotation quality was maintained.

Dataset Statistics
Summarize
number of instances,
class distribution,
document coverage,
chapter or domain coverage,
average lengths,
language,
modality,
any other relevant statistics.
Do not interpret the statistics.

Dataset Usage
Explain how the dataset is used in the study.
Describe
train/validation/test split (if applicable),
evaluation benchmark,
human evaluation subset (if applicable),
downstream tasks,
baseline comparison.
Do not report experimental results.



Reproducibility
The description should provide sufficient information for another researcher to recreate the dataset construction and annotation pipeline.
Clearly describe
collection procedure,
preprocessing,
annotation protocol,
validation,
and quality assurance.

Quality Checklist
Before producing the final Dataset Construction section, verify that
The dataset creation process is described chronologically.
The section clearly states that three independent human annotators manually annotated the dataset.
The annotation guidelines and conflict resolution process are clearly explained.
The annotation schema is fully defined.
The quality control procedure is transparent.
The dataset statistics are descriptive rather than interpretive.
The dataset usage is clearly explained without discussing experimental results.
The writing matches the quality and style of accepted EMNLP Main Track papers.
The section is fully reproducible.
No unsupported claims or invented statistics are introduced.
If any criterion is not satisfied, revise the section before returning the final version.
Return only the completed Dataset Construction section, using polished scientific writing with appropriate subsection headings.

