You are an expert dataset curator specializing in financial document question answering, evidence retrieval, multimodal reasoning, and benchmark dataset construction.



Your task is to generate high-quality QA items from the provided chapter of a financial/economic report.



The dataset must be strictly evidence-grounded. Every question and answer must be directly supported by information explicitly present in the provided source document.



Do NOT use external knowledge, assumptions, background knowledge, or information not contained in the source.





YOU WILL DO MY DATASET DISTRIBUTION MARKDOWN FILE and then generate me chapter wise question so that it keeps aligned with my dataset distribution per chapter wise. 


Direct Factual Retrieval → Easy
Definitional and Classification → Easy
Procedural Reasoning → Medium
Conditional Reasoning → Medium
Comparative Reasoning → Medium
Multi-hop Reasoning → Hard
Hypothetical Legal Reasoning → Hard


Generate evidence-grounded QA items from the provided financial document.

Return ONLY a valid JSON array using exactly this format:

 "id": "LABOURACTQA-CH2-DFR-001",

  "id": "LABOURACTQA-CH2-DEF-001",

[
{
  "id": "",
  "number": 1,
  "category": "",
  "difficulty": "",
  "chapter": "",
  "chapter_title": "",
  "question": "",
  "answer": "",
  "evidence": "",
  "source_page": ""
}
]


Rules

Every answer MUST be directly supported by the evidence.

evidence is mandatory and must contain the exact relevant paragraph text, table values, or chart information.

Do NOT fabricate evidence, paragraph numbers, table/figure numbers, page numbers, or values.

For multiple evidence locations, include all relevant evidence in the same evidence field.

Preserve numerical values, percentages, dates, and units exactly.

Use only information from the provided document; no external knowledge.

query_type should accurately describe the question, such as Fact Extraction, Evidence Retrieval, Multi-Evidence Retrieval, Numerical Reasoning, Comparison, Trend Analysis, Risk Analysis, or Table Interpretation.

difficulty must be Easy, Medium, or Hard.

source_page must identify the page(s) containing the evidence.

Do not add or remove fields.

Priority: Evidence Fidelity > Answer Correctness > Question Quality.