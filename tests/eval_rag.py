
import os
import pandas as pd
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
from datasets import Dataset
from src.rag.retriever import RAGRetriever
from src.inference.engine import InferenceEngine

def run_evaluation(test_cases: list[dict]):
    """
    test_cases: list of {"question": "...", "ground_truth": "..."}
    """
    retriever = RAGRetriever()
    engine = InferenceEngine()

    questions = [tc["question"] for tc in test_cases]
    ground_truths = [tc["ground_truth"] for tc in test_cases]
    
    answers = []
    contexts = []

    print(f"Evaluating {len(test_cases)} cases...")
    for q in questions:
        # 1. Retrieve
        results = retriever.retrieve(q)
        context_text = [r.text for r in results]
        
        # 2. Generate
        formatted_ctx = retriever.format_context(results)
        response = engine.generate(q, context=formatted_ctx)
        
        answers.append(response)
        contexts.append(context_text)

    # Prepare dataset
    dataset = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths
    })

    # Run evaluation
    result = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall]
    )
    
    df = result.to_pandas()
    df.to_csv("rag_eval_results.csv", index=False)
    print("Evaluation complete. Results saved to rag_eval_results.csv")
    print(result)

if __name__ == "__main__":
    # Example test set
    sample_cases = [
        {"question": "What are the 12 steps?", "ground_truth": "The 12 steps are a set of guiding principles for recovery..."},
        {"question": "How does the program view resentment?", "ground_truth": "Resentment is often described as the 'number one offender'..."}
    ]
    run_evaluation(sample_cases)
