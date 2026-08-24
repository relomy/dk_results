from dk_results.analytics.trainfinder import TrainCluster, TrainFinder
from dk_results.domain.user import User


def test_train_analysis_returns_typed_clusters() -> None:
    users = [User(1, "e1", "one", "20", 100.0, ""), User(2, "e2", "two", "20", 100.0, "")]
    clusters = TrainFinder(users).get_users_above_salary_spent(50000)
    assert isinstance(clusters["100.0-20"], TrainCluster)
    assert clusters["100.0-20"].user_count == 2
