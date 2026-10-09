"""Agent control must stay out of the release manifest, and only the debug overlay may declare it."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
ANDROID = "{http://schemas.android.com/apk/res/android}"
AGENT_COMPONENTS = (".agent.AgentStartActivity", ".agent.AgentBridgeProvider")


def declared(manifest):
    """Component names declared under <application>, with their exported and permission attributes."""
    application = ET.parse(manifest).getroot().find("application")
    if application is None:
        return {}
    found = {}
    for element in application:
        name = element.get(ANDROID + "name")
        if name:
            found[name] = (element.get(ANDROID + "exported"), element.get(ANDROID + "permission"))
    return found


class ReleaseManifestTest(unittest.TestCase):
    def test_release_manifest_does_not_declare_agent_components(self):
        found = declared(ROOT / "app/src/main/AndroidManifest.xml")
        for component in AGENT_COMPONENTS:
            self.assertNotIn(component, found)

    def test_no_main_component_is_exported_with_dump_permission(self):
        for name, (_, permission) in declared(ROOT / "app/src/main/AndroidManifest.xml").items():
            self.assertNotEqual(permission, "android.permission.DUMP", name)

    def test_debug_overlay_declares_agent_components_with_dump_permission(self):
        found = declared(ROOT / "app/src/debug/AndroidManifest.xml")
        for component in AGENT_COMPONENTS:
            self.assertIn(component, found)
            self.assertEqual(found[component], ("true", "android.permission.DUMP"))


if __name__ == "__main__":
    unittest.main()
