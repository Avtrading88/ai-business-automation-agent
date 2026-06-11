class HumanApproval:
    """Simple command-line human approval step before external sync."""

    def request(
        self, message: str = "Do you approve sending this clean data to external tools?"
    ) -> bool:
        print("\n" + "=" * 60)
        print("HUMAN APPROVAL REQUIRED")
        print("=" * 60)
        print(message)
        print("Type 'yes' to approve, or anything else to stop.")
        answer = input("Approval: ").strip().lower()
        return answer in {"yes", "y"}
