import pandas as pd

from automation_agent.core.cleaner import DataCleaner


def test_cleaner_normalizes_columns_email_phone_and_names():
    df = pd.DataFrame(
        {
            "First Name": ["  vladimir  "],
            "E-mail": ["  VLADIMIR@EXAMPLE.COM "],
            "Phone Number": [" +49 (123) 456-789 "],
            "Country": [" germany "],
        }
    )

    cleaned = DataCleaner(
        {
            "lowercase_email": True,
            "normalize_phone": True,
            "title_case_names": True,
            "title_case_company": False,
        }
    ).clean(df)

    assert list(cleaned.columns) == ["first_name", "email", "phone", "country"]
    assert cleaned.loc[0, "first_name"] == "Vladimir"
    assert cleaned.loc[0, "email"] == "vladimir@example.com"
    assert cleaned.loc[0, "phone"] == "+49123456789"
    assert cleaned.loc[0, "country"] == "Germany"
