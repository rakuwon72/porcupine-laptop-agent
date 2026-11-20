"""Lists the clickable / typeable parts of an open window, so you can write
accurate actions in the manifest.

Usage (open the page or app first, e.g. the webmail Compose screen):
    python inspect_window.py "IITD Webmail"

The argument is a regex matched against the window title. For each control it
prints the TYPE, the NAME and the AUTO_ID. Put the name in a manifest step like:
    {"method": "click_control", "control": "Send"}
or, when the name is empty, the auto_id:
    {"method": "type_text", "auto_id": "composebody", "field": "body"}
(The agent can do the same by itself with its list_controls tool.)
"""

import sys

from pywinauto import Desktop

from agent.controller import describe_controls


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit('Usage: python inspect_window.py "part of the window title"')

    window = Desktop(backend="uia").window(title_re=f".*{sys.argv[1]}.*", found_index=0)
    window.wait("exists", timeout=5)

    print(f"Window: {window.window_text()!r}")
    print("Reading the window (browsers need a few seconds to expose page contents)...\n")

    controls = describe_controls(window)  # waits until the list stops growing
    for control_type, name, auto_id in controls:
        print(f"{control_type:10} name={name!r:45} auto_id={auto_id!r}")

    print(f"\n{len(controls)} controls listed.")
    if not any(c[0] == "Document" for c in controls):
        print("No web page found inside this window. Make sure the page you want is the")
        print("ACTIVE tab. If it still fails, turn on the browser's accessibility switch:")
        print("  Edge: edge://accessibility -> enable 'Native accessibility API support'")


if __name__ == "__main__":
    main()
