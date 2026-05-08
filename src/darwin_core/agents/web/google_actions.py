from __future__ import annotations

from typing import TYPE_CHECKING

from .prompts import GENDER_OPTIONS, MONTH_NAMES

if TYPE_CHECKING:
    from playwright.sync_api import Page


def try_google_month_select(page: Page, month_name: str) -> bool:
    if "accounts.google.com/lifecycle/steps/signup/birthdaygender" not in page.url:
        return False
    if month_name not in MONTH_NAMES:
        return False
    try:
        selected = page.evaluate(
            """(monthName) => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const month = norm(monthName);
                const monthWords = ['january','february','march','april','may','june','july','august','september','october','november','december'];

                const combos = Array.from(document.querySelectorAll('[role="combobox"]')).filter(visible);
                const monthCombo = combos.find((el) => {
                    const text = norm(el.textContent);
                    return text.includes('month') || monthWords.some((w) => text.includes(w));
                }) || combos[0];
                if (!monthCombo) return false;

                monthCombo.scrollIntoView({ block: 'center', inline: 'nearest' });
                monthCombo.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                monthCombo.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                monthCombo.click();

                const listboxes = Array.from(document.querySelectorAll('[role="listbox"]')).filter(visible);
                let monthList = listboxes.find((el) => norm(el.getAttribute('aria-label')).includes('month'));
                if (!monthList) {
                    monthList = listboxes.find((el) => monthWords.some((w) => norm(el.textContent).includes(w))) || null;
                }
                if (!monthList) return false;

                const candidates = Array.from(monthList.querySelectorAll('[role="option"], li, div, span'))
                    .filter(visible)
                    .filter((el) => norm(el.textContent) === month);
                const target = candidates[0] || null;
                if (!target) return false;

                target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                target.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }));
                target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                target.dispatchEvent(new MouseEvent('click', { bubbles: true }));

                const comboText = norm(monthCombo.textContent);
                return comboText.includes(month);
            }""",
            month_name,
        )
        return bool(selected)
    except Exception:  # noqa: BLE001
        return False


def try_google_gender_select(page: Page, gender_text: str) -> bool:
    if "accounts.google.com/lifecycle/steps/signup/birthdaygender" not in page.url:
        return False
    if gender_text not in GENDER_OPTIONS:
        return False
    try:
        selected = page.evaluate(
            """(targetGender) => {
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                };
                const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const target = norm(targetGender);
                const genderWords = ['female', 'male', 'rather not say', 'custom'];

                const combos = Array.from(document.querySelectorAll('[role="combobox"]')).filter(visible);
                const genderCombo = combos.find((el) => {
                    const text = norm(el.textContent);
                    return text.includes('gender') || genderWords.some((w) => text.includes(w));
                }) || combos[1];
                if (!genderCombo) return false;

                genderCombo.scrollIntoView({ block: 'center', inline: 'nearest' });
                genderCombo.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                genderCombo.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                genderCombo.click();

                const listboxes = Array.from(document.querySelectorAll('[role="listbox"]')).filter(visible);
                let genderList = listboxes.find((el) => norm(el.getAttribute('aria-label')).includes('gender'));
                if (!genderList) {
                    genderList = listboxes.find((el) => genderWords.some((w) => norm(el.textContent).includes(w))) || null;
                }
                if (!genderList) return false;

                const candidates = Array.from(genderList.querySelectorAll('[role="option"], li, div, span'))
                    .filter(visible)
                    .filter((el) => norm(el.textContent) === target);
                const option = candidates[0] || null;
                if (!option) return false;

                option.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                option.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }));
                option.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                option.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                option.dispatchEvent(new MouseEvent('click', { bubbles: true }));

                const comboText = norm(genderCombo.textContent);
                return comboText.includes(target);
            }""",
            gender_text,
        )
        return bool(selected)
    except Exception:  # noqa: BLE001
        return False


def try_google_click_next(page: Page) -> bool:
    if "accounts.google.com" not in page.url:
        return False
    try:
        # Prefer semantic role targeting to avoid matching hidden/secondary "Next" elements.
        page.get_by_role("button", name="Next").first.click(timeout=8000)
        return True
    except Exception:  # noqa: BLE001
        return False

