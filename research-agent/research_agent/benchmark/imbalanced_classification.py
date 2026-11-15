"""Compare logistic regression with and without class weights on synthetic tabular data."""

import argparse
import json

import sklearn
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


SPLIT_SEEDS = (42, 43, 44)


def run_benchmark(split_seed=42):
    data, labels = make_classification(
        n_samples=3000, n_features=12, n_informative=5, n_redundant=2,
        weights=[0.95, 0.05], class_sep=0.8, flip_y=0, random_state=42,
    )
    train_x, test_x, train_y, test_y = train_test_split(
        data, labels, test_size=0.3, stratify=labels, random_state=split_seed,
    )
    summary = {}
    for name, weight in (("unweighted", None), ("balanced", "balanced")):
        model = make_pipeline(StandardScaler(), LogisticRegression(class_weight=weight))
        prediction = model.fit(train_x, train_y).predict(test_x)
        summary[name] = {
            "precision": round(float(precision_score(test_y, prediction, zero_division=0)), 6),
            "recall": round(float(recall_score(test_y, prediction, zero_division=0)), 6),
            "f1": round(float(f1_score(test_y, prediction, zero_division=0)), 6),
            "confusion_matrix": confusion_matrix(test_y, prediction, labels=[0, 1]).tolist(),
        }
    return {
        "summary": summary,
        "configuration": {
            "dataset": "synthetic (sklearn.datasets.make_classification)",
            "data_seed": 42,
            "split_seed": split_seed,
            "model": "StandardScaler + LogisticRegression (lbfgs, C=1, threshold=0.5)",
            "train_rows": len(train_y),
            "test_rows": len(test_y),
            "minority_label": 1,
            "train_minority": int(train_y.sum()),
            "test_minority": int(test_y.sum()),
            "scikit_learn": sklearn.__version__,
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-seed", type=int, choices=SPLIT_SEEDS, default=42)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.split_seed), indent=2))
