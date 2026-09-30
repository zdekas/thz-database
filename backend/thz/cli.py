import argparse
import sys

from . import analysis, auth, db, example, importer, records


def cmd_init_db(args):
    with db.connect("admin") as conn:
        db.init(conn)
    print("database schemas, users and grants are up to date")


def cmd_import(args):
    with db.connect("importer") as conn:
        changed, failed = _import(conn, args)
    if changed:
        with db.connect("analysis") as conn:
            analysis.analyse(conn, changed)
        print(f"analysed {len(changed)} measurement(s) with analysis v{analysis.ANALYSIS_VERSION}")
    if failed:
        sys.exit(f"{failed} folder(s) failed")


def _import(conn, args):
    folders = importer.find_folders(args.path)
    if not folders:
        sys.exit(f"no metadata.yaml found under {args.path}")
    changed, failed = [], 0
    for folder in folders:
        try:
            mid, status = importer.import_folder(conn, folder, update=args.update)
        except (importer.ImportError_, OSError, ValueError) as exc:
            conn.rollback()
            failed += 1
            print(f"FAILED   {folder}: {exc}")
            continue
        if status == "edited":
            print(f"skipped  {folder}: the record was edited on the website and is not overwritten")
            continue
        print(f"{status:8s} {folder}")
        if status != "skipped":
            changed.append(mid)
    return changed, failed


def cmd_analyse(args):
    with db.connect("analysis") as conn:
        slugs = analysis.analyse(conn)
    print(f"rebuilt analysed layer: {len(slugs)} measurement(s), analysis v{analysis.ANALYSIS_VERSION}")


def cmd_list(args):
    with db.connect("web") as conn:
        rows = _list(conn)
    for r in rows:
        print(f"{r['experiment_date']}  {r['slug']:45s} {r['n_waveforms']} waveforms  "
              f"analysis {r['analysis_version'] or '-':8s} {r['sample_name']}")
    print(f"{len(rows)} measurement(s)")


def _list(conn):
    return conn.execute(
        """
        SELECT m.slug, m.experiment_date, m.sample_name, a.analysis_version,
               (SELECT count(*) FROM raw.waveform w WHERE w.measurement_id = m.id) AS n_waveforms
        FROM raw.measurement m LEFT JOIN analysed.transmission a ON a.measurement_id = m.id
        ORDER BY m.experiment_date, m.slug
        """
    ).fetchall()


def cmd_delete(args):
    with db.connect("importer") as conn:
        n = conn.execute("DELETE FROM raw.measurement WHERE slug = %s", [args.slug]).rowcount
    print(f"deleted {args.slug}" if n else f"no measurement with slug {args.slug}")
    if n and (records.UPLOAD_DIR / args.slug).is_dir():
        print(f"its uploaded files are kept in data/uploads/{args.slug}; remove that folder too, "
              f"otherwise `import /data` would add the record again")


def cmd_create_user(args):
    """Also used to reset a password: the account gets a new random one."""
    password = auth.random_password()
    with db.connect("auth") as conn:
        account_id = auth.set_password(conn, args.email, password)
        if args.name is not None:
            conn.execute("UPDATE auth.account SET name = %s WHERE id = %s", [args.name, account_id])
    print(f"account:  {auth.normalise_email(args.email)}")
    print(f"password: {password}")
    print("change it after the first login (Change password on the Add record page)")


def cmd_list_users(args):
    with db.connect("auth") as conn:
        rows = conn.execute("SELECT email, name, created_at FROM auth.account ORDER BY email").fetchall()
    for r in rows:
        print(f"{r['email']:40s} {r['name']:25s} created {r['created_at']:%Y-%m-%d}")
    print(f"{len(rows)} account(s)")


def cmd_delete_user(args):
    with db.connect("auth") as conn:
        n = conn.execute("DELETE FROM auth.account WHERE email = %s", [auth.normalise_email(args.email)]).rowcount
    print(f"deleted {args.email}" if n else f"no account {args.email}")


def main():
    parser = argparse.ArgumentParser(prog="thz")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db", help="create schemas, database users and grants (run by the init service)")
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("import", help="import a measurement folder, or every folder with a metadata.yaml below a path")
    p.add_argument("path")
    p.add_argument("--update", action="store_true", help="replace measurements that are already in the database")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("analyse", help="rebuild the whole analysed layer from raw data")
    p.set_defaults(func=cmd_analyse)

    p = sub.add_parser("list", help="list measurements")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("delete", help="delete one measurement (raw and analysed)")
    p.add_argument("slug")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("create-user", help="create an account with a random password, or reset its password")
    p.add_argument("email")
    p.add_argument("--name", help="shown as 'added by' on records; defaults to the e-mail")
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("list-users", help="list accounts")
    p.set_defaults(func=cmd_list_users)

    p = sub.add_parser("delete-user", help="delete an account")
    p.add_argument("email")
    p.set_defaults(func=cmd_delete_user)

    p = sub.add_parser("make-examples", help="write synthetic example measurement folders")
    p.add_argument("path")
    p.set_defaults(func=None)

    args = parser.parse_args()
    if args.command == "make-examples":
        for folder in example.write_examples(args.path):
            print(f"wrote {folder}")
        return
    args.func(args)
