# ADR-0003: Random Forest як основна модель

- **Статус:** прийнято для прототипу.
- **Контекст:** тема вимагає Random Forest; потрібно мінімізувати складність і мати порівняння з baseline.
- **Варіанти:** Logistic Regression, Random Forest, Isolation Forest, CNN/LSTM.
- **Рішення:** Random Forest класифікує attack/benign; Logistic Regression є простим baseline, Isolation Forest лишається anomaly-comparison методом.
- **Наслідки:** табличні числові дані не потребують складного deep-learning pipeline; для final deployment потрібне калібрування confidence й перевірка data drift.
