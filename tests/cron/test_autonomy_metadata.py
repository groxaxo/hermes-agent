from cron.jobs import create_job


def test_create_job_stores_purpose_and_budget_metadata():
    job = create_job(
        prompt="Summarize daily signals",
        schedule="2099-01-01T00:00:00Z",
        purpose="summarize",
        budget_usd=0.42,
    )

    assert job["purpose"] == "summarize"
    assert job["budget_usd"] == 0.42
