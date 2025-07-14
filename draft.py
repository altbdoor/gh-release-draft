#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "pygithub",
# ]
# ///

import argparse
import difflib
from getpass import getpass
import itertools
import os
import subprocess
from github import Github, Auth
from github.Repository import Repository
from github.GitRelease import GitRelease


BORDER: str = "=" * 40


def main(repo_name: str):
    gh_token = os.getenv("GH_TOKEN", "")
    use_color = os.getenv("NO_COLOR") is None

    if use_color:
        RED = "\033[31m"
        GREEN = "\033[32m"
        RESET = "\033[0m"
    else:
        RED = GREEN = RESET = ""

    if not gh_token:
        try:
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, check=True
            )
            gh_token = result.stdout.strip()
        except:
            pass

    if not gh_token:
        gh_token = getpass("Enter GitHub token: ")

    if not gh_token:
        raise Exception("Unable to get GitHub token")

    auth = Auth.Token(gh_token)
    client = Github(auth=auth)

    release_data = {
        "draft": "",
        "minor": "",
    }

    print(f"Obtaining release info for {repo_name}...")
    repo_ref = client.get_repo(repo_name)
    releases = repo_ref.get_releases().get_page(0)
    draft_release = None

    for r in releases:
        if release_data["draft"] == "" and r.draft:
            release_data["draft"] = r.tag_name
            draft_release = r

        if release_data["minor"] == "" and not r.draft and r.tag_name.endswith(".0"):
            release_data["minor"] = r.tag_name

        if all(v != "" for v in release_data.values()):
            break

    print(BORDER)
    print(f"Latest draft: {release_data['draft'] or '(NONE)'}")
    print(f"Latest minor: {release_data['minor'] or '(NONE)'}")
    print(BORDER)

    if release_data["draft"]:
        confirm_update = input("> Update old draft release? [y/N]: ").strip().lower()
        if confirm_update not in ("y", "yes"):
            print("Exiting")
            return

        print("Retrieving draft release notes...")
        if not isinstance(draft_release, GitRelease) or not draft_release:
            raise Exception("unable to retrieve draft release info")

        prev_release_note = draft_release.body.strip()

        print("Generating release notes...")
        next_release_note = _generate_release_note(
            repo_ref, release_data["minor"], release_data["draft"]
        )

        release_diff = difflib.unified_diff(
            prev_release_note.splitlines(),
            next_release_note.splitlines(),
            fromfile="Current draft",
            tofile="New draft",
        )

        try:
            first_line = next(release_diff)
            release_diff = itertools.chain([first_line], release_diff)
        except StopIteration:
            print("No updates to the release note")
            print("Exiting")
            return

        print(BORDER)
        for line in release_diff:
            if line.startswith("-"):
                print(f"{RED}{line.rstrip()}{RESET}")
            elif line.startswith("+"):
                print(f"{GREEN}{line.rstrip()}{RESET}")
            else:
                print(line.rstrip())
        print(BORDER)

        confirm_update_draft = (
            input("> Update draft release with note? [y/N]: ").strip().lower()
        )
        if confirm_update_draft not in ("y", "yes"):
            print("Exiting")
            return

        print("Updating existing draft release...")
        updated_minor = draft_release.update_release(
            name=release_data["draft"], message=next_release_note, draft=True
        )

        print(f"Updated draft release in {updated_minor.html_url}")
        print("Exiting")

    elif release_data["minor"]:
        confirm_create = input("> Create new draft release? [y/N]: ").strip().lower()
        if confirm_create not in ("y", "yes"):
            print("Exiting")
            return

        next_release = ""
        try:
            next_release_parts = release_data["minor"].rsplit(".")
            if len(next_release_parts) != 3:
                raise Exception("minor release not in semver")

            prefix, minor_str, _ = next_release_parts
            try:
                minor = int(minor_str) + 1
            except ValueError:
                raise Exception("unable to parse release as semver")

            next_release = f"{prefix}.{minor}.0"
        except Exception as e:
            print(f"(!) unable to determine next release version: {e}")
            next_release = (
                input("> Type in your desired next release version: ").strip().lower()
            )

        print(f"Generating release notes {release_data['minor']} -> {next_release}...")
        release_note = _generate_release_note(
            repo_ref, release_data["minor"], next_release
        )
        print(BORDER)
        print(release_note)
        print(BORDER)

        confirm_create_save = (
            input("> Save new draft release with note? [y/N]: ").strip().lower()
        )
        if confirm_create_save not in ("y", "yes"):
            print("Exiting")
            return

        print("Creating new draft release...")
        new_minor = repo_ref.create_git_release(
            tag=next_release, name=next_release, draft=True, generate_release_notes=True
        )
        print(f"Created draft release in {new_minor.html_url}")
        print("Exiting")


def _generate_release_note(repo_ref, prev_release: str, next_release: str) -> str:
    if not isinstance(repo_ref, Repository):
        raise Exception("invalid repo ref passed in")

    # https://github.com/PyGithub/PyGithub/issues/2794
    _, data = repo_ref._requester.requestJsonAndCheck(
        "POST",
        f"{repo_ref.url}/releases/generate-notes",
        input={
            "tag_name": next_release,
            "previous_tag_name": prev_release,
        },
    )

    if not isinstance(data, dict):
        raise Exception("unable to generate release notes")

    if "body" not in data:
        raise Exception("unable to get release notes text")

    release_note: str = data.get("body", "")
    if release_note == "":
        raise Exception("unable to generate release notes")

    return release_note.strip()


def _repo_arg_validator(value: str) -> str:
    parts = value.split("/")
    if len(parts) != 2 or not all(parts):
        raise argparse.ArgumentTypeError(f"Invalid repo name {value}")

    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "A highly opinionated way of creating/updating GitHub release.\n\n"
            "Examples:\n"
            "    python %(prog)s -h\n"
            "    GH_TOKEN='****' python %(prog)s -r mojombo/jekyll\n"
            "    NOCOLOR=1 GH_TOKEN='****' python %(prog)s -r mojombo/jekyll\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-r",
        "--repo",
        type=_repo_arg_validator,
        required=True,
        help="GitHub repo name, e.g. mojombo/jekyll",
    )
    args = parser.parse_args()

    main(args.repo)
