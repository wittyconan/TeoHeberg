import os
import sys
import re
import time
import random
import logging
import tempfile
import json
import html
import base64
from pathlib import Path
from datetime import datetime
from urllib.parse import quote, urlparse, parse_qs
import requests as req

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ──
ACCOUNTS_RAW = os.environ.get("TEOHEBERG", "")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")
LOGIN_URL = "https://manager.teoheberg.fr/login"
SERVERS_URL = "https://manager.teoheberg.fr/servers"
HOME_URL = "https://manager.teoheberg.fr/home"
SCRIPT_DIR = Path(__file__).resolve().parent
SCREEN_DIR = SCRIPT_DIR / "screenshots"

MAX_CAPTCHA = 8
snap_index = 0

# ── 辅助函数 ──

def ensure_dir():
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)

def mask_email(email: str) -> str:
    parts = email.split("@")
    if len(parts) != 2:
        return email[:3] + "***"
    name, domain = parts
    mn = name[0] + "***" if len(name) > 1 else name + "***"
    dp = domain.split(".")
    md = dp[0][0] + "***." + dp[-1] if len(dp) >= 2 else domain[0] + "***"
    return f"{mn}@{md}"

def snap(page, name: str) -> str | None:
    global snap_index
    try:
        snap_index += 1
        ts = datetime.now().strftime("%H%M%S")
        filename = f"{ts}-{snap_index:03d}-{name}.png"
        filepath = str(SCREEN_DIR / filename)
        page.screenshot(path=filepath, full_page=True)
        log.info(f"📸 截图 → {filename}")
        return filepath
    except Exception:
        return None

def parse_account(raw: str) -> dict:
    v = raw.strip()
    sep = "-----"
    i = v.find(sep)
    if i <= 0 or i + len(sep) >= len(v):
        raise ValueError(f"❌ TEOHEBERG 格式错误，应为: 邮箱{sep}密码")
    return {"email": v[:i].strip(), "password": v[i + len(sep):].strip()}

# ── Telegram ──

def send_telegram_media_group(photo_paths: list[str], caption: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        photos = [p for p in photo_paths if p and os.path.isfile(p)]
        if not photos:
            send_telegram_message(caption)
            return
        if len(photos) == 1:
            with open(photos[0], "rb") as f:
                resp = req.post(
                    f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto",
                    data={"chat_id": TG_CHAT_ID, "caption": caption},
                    files={"photo": f},
                    timeout=30,
                )
            log.info("✅ TG 发送成功" if resp.ok else f"⚠️ TG 发送失败: {resp.status_code}")
            return
        media = []
        files = {}
        for idx, path in enumerate(photos[:2]):
            key = f"photo{idx}"
            media.append({
                "type": "photo",
                "media": f"attach://{key}",
                **({"caption": caption} if idx == 0 else {}),
            })
            files[key] = open(path, "rb")
        resp = req.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMediaGroup",
            data={"chat_id": TG_CHAT_ID, "media": json.dumps(media)},
            files=files,
            timeout=30,
        )
        for f in files.values():
            f.close()
        log.info("✅ TG 发送成功" if resp.ok else f"⚠️ TG 发送失败: {resp.status_code}")
    except Exception as e:
        log.warning(f"⚠️ TG 发送异常: {e}")

def send_telegram_message(message: str):
    if not TG_BOT_TOKEN or not TG_CHAT_ID or not message:
        return
    try:
        resp = req.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": message},
            timeout=30,
        )
        log.info("✅ TG 文本发送成功" if resp.ok else f"⚠️ TG 文本发送失败: {resp.status_code}")
    except Exception as e:
        log.warning(f"⚠️ TG 文本异常: {e}")

def format_summary(email_full, renew_state, completed, failure=""):
    lines = [f"账号：{email_full}"]
    if renew_state.get("attempted"):
        ok = "✅ 续期成功！" if renew_state.get("success") else "❌ 续期失败"
        lines.append(f"续期：{ok}")
        before = renew_state.get("before_text", "?")
        after = renew_state.get("after_text", "?")
        lines.append(f"到期：{before} → {after}")
    elif renew_state.get("skipped") and renew_state.get("before_text"):
        lines.append("续期：无需续期")
        lines.append(f"到期：{renew_state['before_text']}")
    elif not renew_state.get("before_text"):
        lines.append("续期：⚠️ 未检测到到期信息")
    if failure:
        lines.append(f"错误：{failure}")
    if completed > 0:
        lines.append(f"广告：执行 {completed} 次")
    else:
        lines.append("广告：今日额度已用完")
    lines.append("")
    lines.append("TeoHeberg Auto Renew")
    return "\n".join(lines)

# ── reCAPTCHA 音频破解（同前面提供的，未改动核心逻辑）──
def find_recaptcha_frame(page, kind):
    for f in page.frames:
        if "recaptcha" in f.url and kind in f.url:
            return f
    return None

def is_recaptcha_solved(page):
    for f in page.frames:
        try:
            token = f.evaluate("document.querySelector(\"textarea[name='g-recaptcha-response']\")?.value")
            if token and len(token) > 30:
                return True
        except Exception:
            pass
    anchor = find_recaptcha_frame(page, "anchor")
    if anchor:
        try:
            checked = anchor.evaluate(
                "document.querySelector('#recaptcha-anchor')?.getAttribute('aria-checked') === 'true'"
            )
            if checked:
                return True
        except Exception:
            pass
    return False

def is_blocked(page):
    bframe = find_recaptcha_frame(page, "bframe")
    if not bframe:
        return False
    try:
        return bframe.evaluate("""() => {
            const h = document.querySelector('.rc-doscaptcha-header-text');
            if (h && h.textContent.toLowerCase().includes('try again later')) return true;
            const e = document.querySelector('.rc-audiochallenge-error-message');
            if (e && e.offsetParent !== null) return true;
            return false;
        }""")
    except Exception:
        return False

def click_recaptcha_checkbox(page):
    log.info("点击 reCAPTCHA 复选框...")
    anchor = find_recaptcha_frame(page, "anchor")
    if not anchor:
        page.wait_for_selector('iframe[src*="anchor"]', timeout=120000)
        anchor = find_recaptcha_frame(page, "anchor")
    if not anchor:
        raise RuntimeError("❌ 未找到 reCAPTCHA anchor frame")
    anchor.click("#recaptcha-anchor", force=True)
    page.wait_for_timeout(3000)

def switch_to_audio(page):
    bframe = find_recaptcha_frame(page, "bframe")
    if not bframe:
        log.warning("⚠️ 未找到 bframe")
        return False
    try:
        already_audio = bframe.evaluate(
            "document.querySelector('#audio-response') !== null && "
            "document.querySelector('#audio-response').offsetParent !== null"
        )
        if already_audio:
            log.info("✅ 已在音频模式")
            return True
    except Exception:
        pass
    for attempt in range(3):
        try:
            bframe.click("#recaptcha-audio-button", force=True, timeout=5000)
            log.info("✅ 已点击音频按钮")
            page.wait_for_timeout(3000)
            is_audio = bframe.evaluate("document.querySelector('#audio-response') !== null")
            if is_audio:
                log.info("✅ 已切换到音频模式")
                return True
        except Exception as e:
            log.warning(f"⚠️ 音频按钮点击方式1失败 (#{attempt+1}): {e}")
        try:
            bframe.evaluate("""() => {
                const btn = document.querySelector('#recaptcha-audio-button');
                if (btn) { btn.click(); return true; }
                return false;
            }""")
            page.wait_for_timeout(3000)
            is_audio = bframe.evaluate("document.querySelector('#audio-response') !== null")
            if is_audio:
                log.info("✅ 已切换到音频模式 (JS)")
                return True
        except Exception as e:
            log.warning(f"⚠️ 音频按钮点击方式2失败 (#{attempt+1}): {e}")
        page.wait_for_timeout(2000)
    log.warning("⚠️ 无法切换到音频模式")
    return False

def is_audio_mode(page):
    bframe = find_recaptcha_frame(page, "bframe")
    if not bframe:
        return False
    try:
        return bframe.evaluate(
            "document.querySelector('#audio-response') !== null && "
            "document.querySelector('#audio-response').offsetParent !== null"
        )
    except Exception:
        return False

def get_audio_url(page):
    bframe = find_recaptcha_frame(page, "bframe")
    if not bframe:
        return None
    for _ in range(10):
        try:
            url = bframe.evaluate("""() => {
                const link = document.querySelector('.rc-audiochallenge-tdownload-link');
                if (link) { const href = link.getAttribute('href'); if (href && href.length > 10) return href; }
                const audio = document.querySelector('#audio-source');
                if (audio) { const src = audio.getAttribute('src'); if (src && src.length > 10) return src; }
                return null;
            }""")
            if url:
                return html.unescape(url)
        except Exception:
            pass
        page.wait_for_timeout(1000)
    log.warning("⚠️ 等待音频 URL 超时")
    return None

def reload_challenge(page):
    bframe = find_recaptcha_frame(page, "bframe")
    if not bframe:
        return
    try:
        bframe.click("#recaptcha-reload-button", force=True)
        log.info("🔄 已重新加载验证码")
        page.wait_for_timeout(3000)
    except Exception:
        pass

def fill_and_verify(page, text):
    bframe = find_recaptcha_frame(page, "bframe")
    if not bframe:
        return False
    try:
        bframe.fill("#audio-response", text)
        log.info("✅ 已填写答案")
    except Exception:
        return False
    page.wait_for_timeout(int(random.uniform(500, 1500)))
    try:
        bframe.click("#recaptcha-verify-button")
        log.info("✅ 已点击验证按钮")
    except Exception:
        pass
    return True

def download_audio(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.google.com/",
    }
    urls = [url]
    if "recaptcha.net" in url:
        urls.append(url.replace("recaptcha.net", "www.google.com"))
    elif "google.com" in url:
        urls.append(url.replace("www.google.com", "recaptcha.net"))
    for u in urls:
        try:
            r = req.get(u, headers=headers, timeout=30)
            r.raise_for_status()
            if len(r.content) < 1000:
                continue
            log.info(f"📥 下载成功: {len(r.content)} bytes")
            p = tempfile.mktemp(suffix=".mp3")
            with open(p, "wb") as f:
                f.write(r.content)
            return p
        except Exception as e:
            log.warning(f"⚠️ 下载失败: {e}")
    return None

def recognize_audio(mp3_path):
    try:
        import speech_recognition as sr
        from pydub import AudioSegment
        wav_path = mp3_path.replace(".mp3", ".wav")
        AudioSegment.from_mp3(mp3_path).export(wav_path, format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as src:
            audio_data = recognizer.record(src)
            text = recognizer.recognize_google(audio_data)
        try:
            os.remove(wav_path)
        except:
            pass
        return text
    except Exception as e:
        log.warning(f"⚠️ 识别失败: {e}")
        return None

def solve_recaptcha(page):
    log.info("🎧 启动 reCAPTCHA 音频破解...")
    start = time.time()
    while time.time() - start < 15:
        if find_recaptcha_frame(page, "anchor"):
            log.info("✅ reCAPTCHA 已加载")
            break
        page.wait_for_timeout(1000)
    else:
        raise RuntimeError("❌ reCAPTCHA 加载超时")
    dl_fails = 0
    for i in range(MAX_CAPTCHA):
        log.info(f"--- 验证码尝试 {i + 1}/{MAX_CAPTCHA} ---")
        if is_recaptcha_solved(page):
            log.info("✅ 验证已通过!")
            return
        if is_blocked(page):
            snap(page, "recaptcha-blocked")
            raise RuntimeError("❌ reCAPTCHA IP 被封锁")
        if i == 0:
            click_recaptcha_checkbox(page)
            snap(page, "recaptcha-checkbox-clicked")
            page.wait_for_timeout(2000)
            if is_recaptcha_solved(page):
                log.info("✅ 复选框直接通过!")
                return
        if not is_audio_mode(page):
            log.info("切换到音频模式...")
            if not switch_to_audio(page):
                log.warning("⚠️ 无法切换音频模式")
                page.wait_for_timeout(3000)
                if not switch_to_audio(page):
                    log.warning("⚠️ 二次尝试切换失败，重新点击复选框")
                    click_recaptcha_checkbox(page)
                    page.wait_for_timeout(3000)
                    continue
            page.wait_for_timeout(int(random.uniform(2000, 4000)))
        snap(page, f"recaptcha-audio-{i + 1}")
        if is_blocked(page):
            snap(page, "recaptcha-blocked")
            raise RuntimeError("❌ reCAPTCHA IP 被封锁")
        audio_url = get_audio_url(page)
        if not audio_url:
            log.warning("⚠️ 未获取到音频 URL")
            bframe = find_recaptcha_frame(page, "bframe")
            if bframe:
                try:
                    inner = bframe.evaluate("document.body?.innerHTML?.substring(0, 500)")
                    log.info(f"🔍 bframe 内容: {inner}")
                except:
                    pass
            reload_challenge(page)
            continue
        mp3 = download_audio(audio_url)
        if not mp3:
            dl_fails += 1
            if dl_fails >= 3:
                raise RuntimeError("❌ 音频连续下载失败")
            reload_challenge(page)
            page.wait_for_timeout(int(random.uniform(3000, 6000)))
            continue
        dl_fails = 0
        text = recognize_audio(mp3)
        try:
            os.remove(mp3)
        except:
            pass
        if not text:
            reload_challenge(page)
            page.wait_for_timeout(3000)
            continue
        log.info(f"🗣️ 识别: [{text}]")
        fill_and_verify(page, text)
        page.wait_for_timeout(5000)
        if is_recaptcha_solved(page):
            log.info("✅ 验证通过!")
            return
        log.warning("⚠️ 验证未通过，重试...")
        reload_challenge(page)
        page.wait_for_timeout(int(random.uniform(2000, 4000)))
    raise RuntimeError("❌ 验证码达到最大尝试次数")

# ── 登录 ──

def do_login(page):
    account = parse_account(ACCOUNTS_RAW)
    log.info("访问登录页...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    snap(page, "login-page")
    log.info(f"当前URL: {page.url}")

    # ── 处理 reCAPTCHA ──
    log.info("处理 reCAPTCHA...")
    solve_recaptcha(page)
    snap(page, "login-captcha-solved")

    # ── 填写表单 ──
    page.fill('input[name="email"]', account["email"])
    page.fill('input[name="password"]', account["password"])
    log.info("☑️ 表单填写完成")
    snap(page, "login-form-filled")

    # ── 提交 ──
    clicked = False
    for sel in [
        'button:has-text("Sign in")',
        'button:has-text("Login")',
        'button[type="submit"]',
        'input[type="submit"]',
    ]:
        loc = page.locator(sel).first
        try:
            if loc.count():
                loc.click(force=True)
                clicked = True
                break
        except Exception:
            continue

    submitted = False
    try:
        submitted = page.evaluate("""() => {
            const form = document.querySelector('form');
            if (!form) return false;
            if (typeof form.requestSubmit === 'function') { form.requestSubmit(); return true; }
            form.submit(); return true;
        }""")
    except Exception:
        pass

    log.info(f"🚀 已提交登录 click={clicked} form={submitted}")
    page.wait_for_timeout(5000)
    snap(page, "login-submitted")
    log.info(f"登录后URL: {page.url}")

    if "login" in page.url.lower():
        snap(page, "login-failed")
        raise RuntimeError("❌ 登录失败，仍在登录页")

    wait_for_dashboard(page)
    log.info("✅ 登录成功")

def wait_for_dashboard(page, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            text = page.locator("body").inner_text()
        except:
            text = ""
        if re.search(r"earn (free )?credits|serveurs|dashboard|tableau de bord", text, re.IGNORECASE):
            snap(page, "dashboard-ready")
            return True
        page.wait_for_timeout(1500)
    snap(page, "dashboard-timeout")
    raise RuntimeError("❌ 未回到 dashboard")

# ── 续期逻辑 ──

def parse_expiry_info(text: str):
    """
    返回 (days_float, descriptive_string)
    """
    # 1. X jours/days left
    m = re.search(r"(\d+)\s*(?:jours?|days?)\s*left", text, re.IGNORECASE)
    if m:
        d = float(m.group(1))
        return d, f"{d:.0f} days left"
    # 2. Xh Ym left
    m = re.search(r"(\d+)\s*h\s*(\d+)\s*m\s*left", text, re.IGNORECASE)
    if m:
        hours = int(m.group(1))
        minutes = int(m.group(2))
        days = hours / 24.0 + minutes / (24.0 * 60.0)
        return days, f"{hours}h {minutes}m left"
    return None, None

def check_and_renew(page) -> tuple[dict, str | None]:
    log.info("=" * 50)
    log.info("检查 Serveurs")
    log.info("=" * 50)
    log.info("ℹ️ 直接打开 Serveurs 页面")
    page.goto(SERVERS_URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(3000)
    serveurs_shot = snap(page, "serveurs-page")
    body_text = ""
    try:
        body_text = page.locator("body").inner_text()
    except:
        pass

    days, before_text = parse_expiry_info(body_text)
    if days is None:
        log.warning("⚠️ 未找到 jours/hours left")
        return {
            "attempted": False, "success": False, "skipped": False,
            "before_text": None, "after_text": None,
        }, serveurs_shot

    log.info(f"📅 剩余 {before_text}")
    if days >= 2:
        log.info("✅ 无需续期")
        return {
            "attempted": False, "success": False, "skipped": True,
            "before_text": before_text, "after_text": None,
        }, serveurs_shot

    log.info(f"⚠️ 剩余不足 2 天，开始续期")

    # 点击 Renew （现在是链接）
    renew_btn = page.get_by_text("Renew", exact=True).first
    renew_btn.wait_for(timeout=15000)
    renew_btn.click(force=True)
    page.wait_for_url("**/renewal", timeout=15000)
    snap(page, "renewal-page")

    log.info("处理续期 reCAPTCHA...")
    solve_recaptcha(page)
    snap(page, "renew-captcha-solved")

    verify_btn = page.locator('button:has-text("Verify & Renew")').first
    verify_btn.wait_for(timeout=10000)
    verify_btn.click(force=True)
    log.info("🚀 已点击 Verify&Renew")
    page.wait_for_timeout(5000)

    try:
        page.wait_for_url("**/servers**", timeout=15000)
    except:
        pass
    renew_shot = snap(page, "renew-done")

    after_body = ""
    try:
        after_body = page.locator("body").inner_text()
    except:
        pass
    after_days, after_text = parse_expiry_info(after_body)

    # 成功判定：after_days 存在，且显著大于之前（容差 10%，防止浮点误差）
    success = after_days is not None and (after_days > days * 0.9)
    if success:
        log.info(f"✅ 续期成功! 新到期: {after_text}")
    else:
        log.warning(f"⚠️ 续期可能失败，旧={before_text} 新={after_text}")

    return {
        "attempted": True,
        "success": success,
        "skipped": False,
        "before_text": before_text,
        "after_text": after_text or "unknown",
    }, renew_shot or serveurs_shot

# ── Linkvertise 直接 verify ──

def extract_verify_url(linkvertise_url: str) -> str | None:
    try:
        parsed = urlparse(linkvertise_url)
        qs = parse_qs(parsed.query)
        r_param = qs.get("r", [None])[0]
        if not r_param:
            if "linkvertise/verify" in linkvertise_url:
                return linkvertise_url
            return None
        decoded = base64.urlsafe_b64decode(r_param + "=" * (-len(r_param) % 4)).decode("utf-8")
        return decoded
    except Exception as e:
        log.warning(f"⚠️ 解析 Linkvertise URL 失败: {e}")
        return None

def click_earn_and_get_link(page, round_num):
    current_url = page.url
    if "manager.teoheberg.fr" not in current_url:
        log.info(f"ℹ️ [#{round_num}] 不在管理页面，导航回去")
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        snap(page, f"r{round_num}-navigated-home")

    log.info("等待 Earn Credits 按钮...")
    earn = page.get_by_text("Earn Credits").first
    earn.wait_for(timeout=30000)
    log.info(f"✅ [#{round_num}] Earn Credits 可见")
    snap(page, f"r{round_num}-earn-visible")

    earn.click(force=True)
    page.wait_for_timeout(2000)
    snap(page, f"r{round_num}-earn-clicked")

    start = time.time()
    reclick_count = 0
    while time.time() - start < 60:
        try:
            text = page.locator("body").inner_text()
        except:
            text = ""
        if re.search(r"limite quotidienne atteinte", text, re.IGNORECASE):
            log.info("🏁 Limite quotidienne atteinte")
            snap(page, f"r{round_num}-limite")
            return {"url": None, "verify_url": None, "done": True}

        cta = page.get_by_text("Commencer maintenant", exact=True).first
        try:
            cta_visible = cta.is_visible()
        except:
            cta_visible = False
        if cta_visible:
            log.info(f"✅ [#{round_num}] Commencer maintenant 可见")
            snap(page, f"r{round_num}-commencer-visible")
            pages_before = len(page.context.pages)
            url_before = page.url

            popup = None
            try:
                with page.expect_popup(timeout=10000) as popup_info:
                    cta.click(force=True)
                popup = popup_info.value
            except:
                pass
            snap(page, f"r{round_num}-commencer-clicked")

            link_url = None
            if popup:
                link_url = popup.url
                log.info(f"🔗 [#{round_num}] Linkvertise (popup): {link_url}")
                snap(popup, f"r{round_num}-popup-linkvertise")
                try:
                    popup.close()
                except:
                    pass
            else:
                page.wait_for_timeout(3000)
                current_pages = page.context.pages
                if len(current_pages) > pages_before:
                    for p in current_pages:
                        if p == page:
                            continue
                        if p.url and p.url != "about:blank":
                            link_url = p.url
                            log.info(f"🔗 [#{round_num}] Linkvertise (new tab): {link_url}")
                            try:
                                p.close()
                            except:
                                pass
                            break
                if not link_url and page.url != url_before:
                    link_url = page.url
                    log.info(f"🔗 [#{round_num}] Linkvertise (same tab): {link_url}")

            if link_url:
                verify = extract_verify_url(link_url)
                log.info(f"🔓 [#{round_num}] 破解广告链接")
                snap(page, f"r{round_num}-linkvertise")
                return {"url": link_url, "verify_url": verify, "done": False}

            log.warning("⚠️ 未捕获到 Linkvertise 链接，重试")
            snap(page, f"r{round_num}-commencer-no-nav")
            raise RuntimeError(f"❌ [#{round_num}] Commencer 点击后未获取到链接")

        if time.time() - start > 15 and reclick_count < 3:
            try:
                if earn.is_visible():
                    reclick_count += 1
                    log.info(f"🔄 [#{round_num}] 重新点击 Earn Credits (#{reclick_count})")
                    earn.click(force=True)
                    snap(page, f"r{round_num}-earn-reclick-{reclick_count}")
            except:
                pass
        page.wait_for_timeout(2000)

    snap(page, f"r{round_num}-commencer-timeout")
    raise RuntimeError(f"❌ [#{round_num}] 等待 Commencer maintenant 超时")

def direct_verify_and_wait(page, verify_url, round_num):
    log.info(f"🚀 [#{round_num}] 直接访问破解链接")
    page.goto(verify_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    snap(page, f"r{round_num}-verify-loaded")

    start = time.time()
    while time.time() - start < 90:
        try:
            text = page.locator("body").inner_text()
        except:
            text = ""
        if re.search(r"earn (free )?credits", text, re.IGNORECASE):
            log.info(f"✅ [#{round_num}] 回到 Earn Credits")
            snap(page, f"r{round_num}-back-to-earn")
            return page
        if re.search(r"success|vérifié|verified", text, re.IGNORECASE):
            log.info(f"✅ [#{round_num}] 验证成功提示，等待跳转")
            page.wait_for_timeout(2000)
        page.wait_for_timeout(2000)
    snap(page, f"r{round_num}-wait-earn-timeout")
    raise RuntimeError(f"❌ [#{round_num}] 等待返回 Earn Credits 超时")

# ── 主流程 ──

def run():
    from playwright.sync_api import sync_playwright

    ensure_dir()
    account = parse_account(ACCOUNTS_RAW)
    masked = mask_email(account["email"])
    renew_state = {}
    completed_ads = 0
    serveurs_shot = None
    limite_shot = None

    log.info(f"发现账号: {masked}")
    log.info("=" * 50)
    log.info(f"处理账号: {masked}")
    log.info("=" * 50)

    profile = tempfile.mkdtemp(prefix="pw-")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile,
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1920, "height": 1080},
        )

        try:
            page = context.new_page()

            log.info("===== 登录 =====")
            do_login(page)

            renew_state, serveurs_shot = check_and_renew(page)
            wait_for_dashboard(page)

            current_page = page
            for round_num in range(1, 100):
                log.info("")
                log.info(f"===== 第 {round_num} 轮 =====")

                result = click_earn_and_get_link(current_page, round_num)
                if result["done"]:
                    completed = round_num - 1
                    limite_shot = snap(current_page, "limite-final")
                    if completed == 0:
                        log.info("🏁 已跳过广告链接（今日已达上限）")
                    else:
                        log.info(f"🏁 完成 {completed} 次广告链接")
                    summary = format_summary(account["email"], renew_state, completed)
                    send_telegram_media_group([serveurs_shot, limite_shot], summary)
                    log.info("🎉 全部完成")
                    return

                verify_url = result.get("verify_url")
                if verify_url:
                    current_page = direct_verify_and_wait(current_page, verify_url, round_num)
                else:
                    log.error("❌ 无法获取 破解链接，脚本终止")
                    raise RuntimeError("Missing verify URL")

                completed_ads = round_num
                delay = 3 + random.random() * 4
                log.info(f"⏳ 等待 {delay:.0f}s...")
                current_page.wait_for_timeout(int(delay * 1000))

        except Exception as e:
            failure = str(e)
            log.error(f"❌ 异常: {failure}")
            summary = format_summary(account["email"], renew_state, completed_ads, failure)
            try:
                main_page = page if "page" in dir() else context.pages[0]
                error_shot = snap(main_page, "error")
                send_telegram_media_group([serveurs_shot, error_shot], summary)
            except:
                send_telegram_message(summary)
            raise
        finally:
            context.close()

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        log.error(e)
        sys.exit(1)
