"use client";

import { type FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Eye, EyeSlash } from "@phosphor-icons/react";

import { apiJson } from "../lib/api";

type Mode = "login" | "register";
type Account = { email: string; role: string; book_import_count: number; book_import_limit: number | null; must_change_password: boolean };

export function AccountExperience({ initialMode }: { initialMode: Mode }) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [account, setAccount] = useState<Account>();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [message, setMessage] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [isPasswordVisible, setIsPasswordVisible] = useState(false);
  const [isCurrentPasswordVisible, setIsCurrentPasswordVisible] = useState(false);
  const [isNewPasswordVisible, setIsNewPasswordVisible] = useState(false);

  useEffect(() => {
    apiJson<Account>("/auth/session", undefined, { redirectOnUnauthorized: false }).then(setAccount).catch(() => undefined);
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    try {
      const next = await apiJson<Account>(mode === "login" ? "/auth/login" : "/auth/register", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mode === "login" ? { email, password } : { email, password, invite_code: inviteCode }),
      }, { redirectOnUnauthorized: false });
      setAccount(next);
      const destination = new URLSearchParams(window.location.search).get("next");
      window.location.assign(destination?.startsWith("/") && !destination.startsWith("//") ? destination : "/");
    } catch (error) { setMessage(error instanceof Error ? error.message : "账号请求失败。"); }
  }

  async function logout() {
    await apiJson("/auth/logout", { method: "POST" }, { redirectOnUnauthorized: false });
    setAccount(undefined);
  }

  function switchMode() {
    setMode((currentMode) => currentMode === "login" ? "register" : "login");
    setPassword("");
    setIsPasswordVisible(false);
    setMessage("");
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    try {
      await apiJson("/auth/change-password", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: password, new_password: newPassword }),
      }, { redirectOnUnauthorized: false });
      setAccount(undefined);
      setPassword("");
      setNewPassword("");
      setMessage("密码已修改，请使用新密码重新登录。");
    } catch (error) { setMessage(error instanceof Error ? error.message : "密码修改失败。"); }
  }

  if (account) {
    const accountSummary = account.role === "owner"
      ? "主账号 · 导入不限"
      : `体验用户 · 已导入 ${account.book_import_count} / ${account.book_import_limit} 本`;

    return (
      <main className="account-settings-page">
        <header className="account-settings-topbar">
          <Link className="account-settings-brand" href="/">BookThinking</Link>
          <Link className="account-settings-back" href="/"><span aria-hidden="true">←</span> 返回书架</Link>
        </header>

        <div className="account-settings-shell">
          <aside className="account-settings-identity" aria-label="当前账号">
            <div>
              <span className="account-settings-avatar" aria-hidden="true">{account.email.charAt(0).toUpperCase()}</span>
              <p className="account-settings-email">{account.email}</p>
              <p className="account-settings-meta">{accountSummary}</p>
            </div>

            {account.role === "owner" && <Link className="account-settings-admin" href="/admin">管理体验账号</Link>}

            <button className="account-settings-logout" type="button" onClick={() => void logout()}>退出登录</button>
          </aside>

          <section className="account-settings-content" aria-labelledby="account-settings-heading">
            <h1 id="account-settings-heading">账号设置</h1>

            <form className="account-password-form" onSubmit={changePassword}>
              <h2>修改密码</h2>
              {account.must_change_password && <p className="account-settings-message" role="alert">这是临时密码，请立即修改。</p>}

              <label className="account-password-field">
                <span>当前密码</span>
                <span className="account-password-input">
                  <input
                    aria-label="当前密码"
                    autoComplete="current-password"
                    placeholder="请输入当前密码"
                    type={isCurrentPasswordVisible ? "text" : "password"}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                  />
                  <button
                    aria-label={isCurrentPasswordVisible ? "隐藏当前密码" : "显示当前密码"}
                    type="button"
                    onClick={() => setIsCurrentPasswordVisible((visible) => !visible)}
                  >
                    {isCurrentPasswordVisible ? <EyeSlash aria-hidden="true" size={22} /> : <Eye aria-hidden="true" size={22} />}
                  </button>
                </span>
              </label>

              <label className="account-password-field">
                <span>新密码</span>
                <span className="account-password-input">
                  <input
                    aria-label="新密码"
                    autoComplete="new-password"
                    placeholder="请输入新密码"
                    type={isNewPasswordVisible ? "text" : "password"}
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    required
                  />
                  <button
                    aria-label={isNewPasswordVisible ? "隐藏新密码" : "显示新密码"}
                    type="button"
                    onClick={() => setIsNewPasswordVisible((visible) => !visible)}
                  >
                    {isNewPasswordVisible ? <EyeSlash aria-hidden="true" size={22} /> : <Eye aria-hidden="true" size={22} />}
                  </button>
                </span>
              </label>

              {message && <p className="account-settings-message" role="alert">{message}</p>}
              <button className="account-password-submit" type="submit">修改密码</button>
            </form>
          </section>
        </div>
      </main>
    );
  }

  return (
    <main className="account-auth-page">
      <section className="account-auth-intro" aria-labelledby="account-auth-heading">
        <h1 id="account-auth-heading">读懂一本书，从可回查的结论开始。</h1>
        <p>从全书框架进入每章的问题、结论与论证，并随时回到原文证据。</p>
      </section>

      <section className="account-auth-action">
        <form className="account-auth-form" aria-label={mode === "login" ? "登录 BookThinking" : "注册 BookThinking"} onSubmit={submit}>
          <label className="account-auth-field">
            <span>邮箱</span>
            <input
              aria-label="邮箱"
              autoComplete="email"
              placeholder="请输入邮箱"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>

          {mode === "register" && (
            <label className="account-auth-field">
              <span>邀请码</span>
              <input
                aria-label="邀请码"
                autoComplete="off"
                placeholder="请输入邀请码"
                value={inviteCode}
                onChange={(event) => setInviteCode(event.target.value)}
                required
              />
            </label>
          )}

          <label className="account-auth-field">
            <span>密码</span>
            <span className="account-auth-password">
              <input
                aria-label="密码"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                placeholder="请输入密码"
                type={isPasswordVisible ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button
                aria-label={isPasswordVisible ? "隐藏密码" : "显示密码"}
                className="account-auth-password-toggle"
                type="button"
                onClick={() => setIsPasswordVisible((visible) => !visible)}
              >
                {isPasswordVisible ? <EyeSlash aria-hidden="true" size={23} weight="regular" /> : <Eye aria-hidden="true" size={23} weight="regular" />}
              </button>
            </span>
          </label>

          {message && <p className="account-auth-message" role="alert">{message}</p>}

          <button className="account-auth-submit" type="submit">{mode === "login" ? "登录" : "创建账号"}</button>

          <p className="account-auth-switch">
            <span>{mode === "login" ? "还没有账号？" : "已有账号？"}</span>
            <button type="button" onClick={switchMode}>
              {mode === "login" ? "使用邀请码注册" : "返回登录"}
            </button>
          </p>
        </form>
      </section>
    </main>
  );
}
