/**
 * Copy text to the clipboard, returning whether it worked.
 *
 * navigator.clipboard only exists in a secure context, so a LetterFeed served
 * over plain http on a LAN address does not have it at all. Falling back to the
 * deprecated execCommand keeps the copy buttons working there, and returning a
 * boolean lets callers tell the user when neither path succeeded rather than
 * failing silently.
 */
export async function copyText(text: string): Promise<boolean> {
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch {
        // Permission denied or an insecure context: try the fallback below.
    }

    try {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.top = "0";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        textarea.setSelectionRange(0, text.length);
        const copied = document.execCommand("copy");
        document.body.removeChild(textarea);
        return copied;
    } catch {
        return false;
    }
}
