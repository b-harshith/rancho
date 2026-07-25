import json
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix

def get_fee_bracket(fee):
    if fee is None:
        return None
    if fee <= 45000:
        return "Budget"
    elif fee <= 75000:
        return "Affordable"
    elif fee <= 150000:
        return "Premium"
    else:
        return "Luxury"

def extract_features(school):
    meta = school.get("metadata", {})
    analysis = school.get("analysis_dimensions", {})
    enrollment = school.get("enrollment", {})
    loc = meta.get("location", {})
    
    # Calculate age
    established_year_str = meta.get("established_year", "")
    age = np.nan
    if established_year_str and str(established_year_str).isdigit():
        age = datetime.now().year - int(established_year_str)
        
    return {
        "udise_code": school.get("udise_code"),
        "management": analysis.get("management_group", "Unknown"),
        "board": analysis.get("board_group", "Unknown") or "Unknown",
        "school_level": analysis.get("school_level", "Unknown"),
        "gender": analysis.get("gender_group", "Unknown"),
        "language": analysis.get("language_group", "Unknown"),
        "age": age,
        "total_students": enrollment.get("total_students", np.nan),
        "district": loc.get("district", "Unknown"),
        "block": loc.get("block", "Unknown")
    }

def main():
    print("Loading data...")
    input_path = "data/output/schools_analysis_with_fees.json"
    with open(input_path, "r") as f:
        data = json.load(f)
        
    schools = data.get("schools", [])
    
    # Process into lists
    records = []
    
    for s in schools:
        feats = extract_features(s)
        fee_info = s.get("fee_information")
        
        target = None
        is_estimated = False
        
        if fee_info:
            fee = fee_info.get("average_annual_fee")
            if fee is not None:
                target = get_fee_bracket(fee)
                is_estimated = fee_info.get("is_fee_estimated", False)
                
        feats["target"] = target
        feats["is_estimated"] = is_estimated
        records.append(feats)
        
    df = pd.DataFrame(records)
    print(f"Total schools: {len(df)}")
    
    labeled_df = df[df["target"].notnull()].copy()
    unlabeled_df = df[df["target"].isnull()].copy()
    
    print(f"Labeled: {len(labeled_df)}, Unlabeled: {len(unlabeled_df)}")
    
    raw_df = labeled_df[~labeled_df["is_estimated"]].copy()
    est_df = labeled_df[labeled_df["is_estimated"]].copy()
    
    print(f"Raw labels: {len(raw_df)}, Estimated labels: {len(est_df)}")
    
    # Features
    categorical_features = ["management", "board", "school_level", "gender", "language", "district"] # exclude block to avoid massive dimensionality
    numeric_features = ["age", "total_students"]
    
    X_raw = raw_df[categorical_features + numeric_features]
    y_raw = raw_df["target"]
    
    # Split raw into train and test
    X_raw_train, X_raw_test, y_raw_train, y_raw_test = train_test_split(
        X_raw, y_raw, test_size=0.2, random_state=42, stratify=y_raw
    )
    
    X_est = est_df[categorical_features + numeric_features]
    y_est = est_df["target"]
    
    # Combine training sets
    X_train = pd.concat([X_raw_train, X_est], ignore_index=True)
    y_train = pd.concat([y_raw_train, y_est], ignore_index=True)
    
    # Create sample weights
    # Raw weight = 1.0, Est weight = 0.3
    weights = np.array([1.0] * len(X_raw_train) + [0.3] * len(X_est))
    
    # We also want class balancing
    from sklearn.utils.class_weight import compute_class_weight
    classes = np.unique(y_train)
    class_weights = compute_class_weight(class_weight="balanced", classes=classes, y=y_train)
    cw_dict = dict(zip(classes, class_weights))
    
    # Apply class weights to sample weights
    for i, label in enumerate(y_train):
        weights[i] *= cw_dict[label]
        
    # Preprocessing pipeline
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", SimpleImputer(strategy="median"), numeric_features),
            ("cat", Pipeline([
                ("imputer", SimpleImputer(strategy="constant", fill_value="Unknown")),
                ("ohe", OneHotEncoder(handle_unknown="ignore", sparse_output=False))
            ]), categorical_features)
        ]
    )
    
    # Model
    model = RandomForestClassifier(
        n_estimators=100, 
        max_depth=10, 
        random_state=42
    )
    
    pipeline = Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", model)
    ])
    
    print("Training model...")
    # Scikit-learn Pipeline doesn't support sample_weight directly in fit for all versions easily without **kwargs
    # So we fit preprocessor first
    X_train_processed = preprocessor.fit_transform(X_train)
    model.fit(X_train_processed, y_train, sample_weight=weights)
    
    print("\n--- Evaluation on held-out RAW data ---")
    X_raw_test_processed = preprocessor.transform(X_raw_test)
    y_pred = model.predict(X_raw_test_processed)
    print(classification_report(y_raw_test, y_pred))
    print("Confusion Matrix:")
    # We define labels to keep order
    labels_order = ["Budget", "Affordable", "Premium", "Luxury"]
    cm = confusion_matrix(y_raw_test, y_pred, labels=labels_order)
    cm_df = pd.DataFrame(cm, index=labels_order, columns=labels_order)
    print(cm_df)
    
    print("\n--- Inference on Unlabeled Data ---")
    X_unlabeled = unlabeled_df[categorical_features + numeric_features]
    X_unlabeled_processed = preprocessor.transform(X_unlabeled)
    y_unlabeled_pred = model.predict(X_unlabeled_processed)
    
    # Let's get probabilities too
    y_unlabeled_proba = model.predict_proba(X_unlabeled_processed)
    
    unlabeled_df["predicted_target"] = y_unlabeled_pred
    unlabeled_df["confidence"] = np.max(y_unlabeled_proba, axis=1)
    
    print("\nPredicted Distribution on Unlabeled Data:")
    print(unlabeled_df["predicted_target"].value_counts(normalize=True) * 100)
    
    # Add predictions back to JSON
    print("Saving to JSON...")
    
    # We can create a dictionary of udise_code -> prediction
    preds_dict = dict(zip(unlabeled_df["udise_code"], zip(unlabeled_df["predicted_target"], unlabeled_df["confidence"])))
    
    for s in schools:
        udise = s.get("udise_code")
        if udise in preds_dict:
            pred_cat, conf = preds_dict[udise]
            if "analysis_dimensions" not in s:
                s["analysis_dimensions"] = {}
            s["analysis_dimensions"]["fee_group"] = pred_cat
            s["analysis_dimensions"]["fee_group_confidence"] = float(conf)
            
    output_path = "data/output/schools_analysis_predicted_fees.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
        
    print(f"Saved to {output_path}")

if __name__ == "__main__":
    main()
