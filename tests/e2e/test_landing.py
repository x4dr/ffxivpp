from playwright.sync_api import Page


def test_landing_page_offers_both_tools(page: Page, live_server) -> None:
    """The public landing page is the one page that needs no auth.

    The old version of this test opened /party/Default, was redirected to
    Discord's OAuth page, and asserted that the external page had a title. It
    proved nothing about this application. The chooser is a real page and a
    real check of the server and the template.
    """
    page.goto(live_server.url() + "/")

    assert "ffxivpp" in page.title()
    assert page.locator("#surface-party").is_visible()
    assert page.locator("#surface-trainer").is_visible()
    assert page.locator("#surface-quests").is_visible()
