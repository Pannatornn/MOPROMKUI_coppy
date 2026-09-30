from getpass import getpass

from werkzeug.security import generate_password_hash


def main() -> None:
    first = getpass("Staff password (at least 14 characters): ")
    second = getpass("Confirm staff password: ")
    if first != second:
        raise SystemExit("Passwords do not match.")
    if len(first) < 14:
        raise SystemExit("Password must be at least 14 characters.")
    print(generate_password_hash(first, method="scrypt"))


if __name__ == "__main__":
    main()

