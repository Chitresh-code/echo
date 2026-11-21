from pathlib import Path

import pytest

from app import jail


SCRIPT = Path("/data/commands/x.sh")


def _pairs(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


def test_identity_mounts_and_command(settings, ws_id):
    argv = jail.build_argv(settings, ws_id, SCRIPT, 10, lib64_exists=False)
    ws = f"{settings.data_dir}/workspaces/{ws_id}"
    assert argv[:3] == ["nsjail", "-Mo", "--really_quiet"]
    assert _pairs(argv, "-u") == ["1000:1000"] and _pairs(argv, "-g") == ["1000:1000"]
    assert _pairs(argv, "-R") == ["/bin", "/lib", "/usr", "/etc", "/dev/null", "/dev/zero", "/dev/random", "/dev/urandom", str(SCRIPT)]
    assert _pairs(argv, "-B") == [ws, f"{settings.data_dir}/homes/{ws_id}:/home/echo"]
    assert _pairs(argv, "--cwd") == [ws]
    assert _pairs(argv, "-t") == ["10"] and _pairs(argv, "--rlimit_cpu") == ["10"]
    assert _pairs(argv, "--rlimit_as") == ["max"]
    assert "--use_cgroupv2" in argv and _pairs(argv, "--cgroupv2_mount") == ["/sys/fs/cgroup/jails"]
    assert _pairs(argv, "--cgroup_mem_max") == [str(4096 * 1024 * 1024)] and _pairs(argv, "--cgroup_mem_swap_max") == ["0"]
    assert _pairs(argv, "--cgroup_pids_max") == ["1024"]
    assert argv[-3:] == ["--", "/bin/sh", str(SCRIPT)]


def test_lib64_only_when_present(settings, ws_id):
    assert "/lib64" in _pairs(jail.build_argv(settings, ws_id, SCRIPT, 5, lib64_exists=True), "-R")


def test_env_is_an_allowlist(settings, ws_id):
    argv = jail.build_argv(settings, ws_id, SCRIPT, 5, env={"FOO": "a b=c"})
    env = _pairs(argv, "-E")
    assert "HOME=/home/echo" in env and "FOO=a b=c" in env
    assert not any(e.startswith(("ANTHROPIC", "OPENAI", "RUNNER_")) for e in env)


@pytest.mark.parametrize("env", [{"1BAD": "x"}, {"A-B": "x"}, {"OK": "a\0b"}, {"": "x"}])
def test_bad_env_rejected(settings, ws_id, env):
    with pytest.raises(jail.JailError) as e:
        jail.build_argv(settings, ws_id, SCRIPT, 5, env=env)
    assert e.value.code == "invalid_env"


def test_network_flag(settings, ws_id):
    assert "--disable_clone_newnet" in jail.build_argv(settings, ws_id, SCRIPT, 5)
    off = jail.Settings(settings.data_dir, network=False, timeout_max=30, memory_mb=4096)
    assert "--disable_clone_newnet" not in jail.build_argv(off, ws_id, SCRIPT, 5)


def test_cwd_inside_workspace(settings, ws_id):
    ws = f"{settings.data_dir}/workspaces/{ws_id}"
    assert _pairs(jail.build_argv(settings, ws_id, SCRIPT, 5, cwd=f"{ws}/src/../app"), "--cwd") == [f"{ws}/app"]


@pytest.mark.parametrize("cwd", ["relative", "/etc", "{ws}/../other", "{ws}x", "{ws}/\0"])
def test_cwd_outside_workspace_rejected(settings, ws_id, cwd):
    ws = f"{settings.data_dir}/workspaces/{ws_id}"
    with pytest.raises(jail.JailError) as e:
        jail.build_argv(settings, ws_id, SCRIPT, 5, cwd=cwd.format(ws=ws))
    assert e.value.code == "invalid_cwd"


@pytest.mark.parametrize("bad", ["", "ABCDEF" * 6, "../" + "a" * 29, "a" * 31, "a" * 33, "g" * 32])
def test_workspace_id_checked(settings, bad):
    with pytest.raises(jail.JailError):
        jail.build_argv(settings, bad, SCRIPT, 5)


def test_nul_in_command_rejected(settings):
    with pytest.raises(jail.JailError):
        jail.write_script(settings, "echo\0")


def test_script_is_readable_by_the_jail_only_as_a_file(settings):
    jail.commands_dir(settings).mkdir()
    script = jail.write_script(settings, "echo hi")
    assert script.read_text() == "echo hi" and oct(script.stat().st_mode & 0o777) == "0o644"


def test_timeout_capped(settings):
    assert jail.effective_timeout(settings, 9999) == 30
    assert jail.effective_timeout(settings, None) == 30
    assert jail.effective_timeout(settings, 7) == 7
    with pytest.raises(jail.JailError):
        jail.effective_timeout(settings, 0)
