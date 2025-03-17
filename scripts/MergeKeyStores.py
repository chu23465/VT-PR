#!/usr/bin/env python3

import argparse
import json
import sqlite3

from vinetrimmer.utils.AtomicSQL import AtomicSQL

parser = argparse.ArgumentParser(
    "Key Store DB merger",
    description="Simple script to merge vinetrimmer key store db's into one"
)
parser.add_argument(
    "-i", "--input",
    help="key store db that will send keys",
    required=True)
parser.add_argument(
    "-o", "--output",
    help="key store db that will receive keys",
    required=True)
args = parser.parse_args()

add_count = 0
update_count = 0
existed_count = 0

input_db = AtomicSQL()
input_db_id = input_db.load(sqlite3.connect(args.input))

output_db = AtomicSQL()
output_db_id = output_db.load(sqlite3.connect(args.output))

# get all keys from input db
input_keys = input_db.safe_execute(
    input_db_id,
    lambda db, cursor: cursor.execute("SELECT * FROM `keys`")
).fetchall()

for i, service, title, pssh_b64, pssh_sha1, content_keys in input_keys:
    exists = output_db.safe_execute(
        output_db_id,
        lambda db, cursor: cursor.execute(
            """
            SELECT "id","service","title","pssh_b64","pssh_sha1","content_keys" FROM `keys` WHERE `service`=:service AND
            (`pssh_b64`=:pssh_b64 or `pssh_sha1`=:pssh_sha1)
            """,
            {
                "service": service,
                "pssh_b64": pssh_b64,
                "pssh_sha1": pssh_sha1
            }
        )
    ).fetchone()
    if exists:
        has_differences = (
                json.loads(exists[5]) != json.loads(content_keys) or
                title != exists[2] or
                pssh_b64 != exists[3] or
                pssh_sha1 != exists[4]
        )
        if has_differences:
            update_count += 1
            content_keys = list(set(json.loads(exists[5])) | set(json.loads(content_keys)))
            print(f"Updating {title} {service} {pssh_b64}: {content_keys}")
            output_db.safe_execute(
                output_db_id,
                lambda db, cursor: cursor.execute(
                    """
                    UPDATE `keys` SET `service`=:service, `title`=:title, `pssh_b64`=:new_pssh_b64,
                    `pssh_sha1`=:new_pssh_sha1, `content_keys`=:content_keys WHERE `service`=:service AND
                    (`pssh_b64`=:pssh_b64 or `pssh_sha1`=:pssh_sha1)
                    """,
                    {
                        "service": service,
                        "title": title or exists[2],
                        "pssh_b64": pssh_b64,
                        "new_pssh_b64": pssh_b64 or exists[3],
                        "pssh_sha1": pssh_sha1,
                        "new_pssh_sha1": pssh_sha1 or exists[4],
                        "content_keys": json.dumps(content_keys, separators=(",", ":"))
                    }
                )
            )
        else:
            existed_count += 1
            print(f"Key {title} {service} {pssh_b64} already exists in the db with no differences, skipping...")
    else:
        add_count += 1
        print(f"Adding {title} {service} {pssh_b64}: {content_keys}")
        output_db.safe_execute(
            output_db_id,
            lambda db, cursor: cursor.execute(
                """
                INSERT INTO `keys` (service, title, pssh_b64, pssh_sha1, content_keys)
                VALUES (:service, :title, :pssh_b64, :pssh_sha1, :content_keys)
                """,
                {
                    "service": service,
                    "title": title,
                    "pssh_b64": pssh_b64,
                    "pssh_sha1": pssh_sha1,
                    "content_keys": json.dumps(content_keys, separators=(",", ":"))
                }
            )
        )

output_db.commit(output_db_id)

print(
    "Done!\n"
    f"{add_count} added, {update_count} updated in some way, {existed_count} already existed (no difference)"
)
