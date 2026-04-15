#!/usr/bin/env python3
"""Terminal-themed CLI client for Professor Tux."""

import sys
import time
import threading
import itertools
import requests

API = "http://localhost:8000"

# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    BRIGHT_GREEN = "\033[38;5;82m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[95m"
    RED = "\033[91m"
    BLACK_BG = "\033[40m"

def clear():
    """Clear terminal screen."""
    print("\033[2J\033[H", end="")

def typewrite(text, delay=0.008, color=Colors.BRIGHT_GREEN):
    """Print text with typing animation."""
    print(color, end="")
    for char in text:
        print(char, end="", flush=True)
        time.sleep(delay)
    print(Colors.RESET, end="")

def print_prompt(user="student", host="cybersec-lab", path="~"):
    """Print a terminal-style prompt."""
    print(f"{Colors.GREEN}┌──({Colors.CYAN}{user}@{host}{Colors.GREEN})-[{Colors.YELLOW}{path}{Colors.GREEN}]{Colors.RESET}")
    print(f"{Colors.GREEN}└─{Colors.BOLD}${Colors.RESET} ", end="")

def spinner_event(stop_event, message="Processing"):
    """Show a spinner while processing."""
    spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
    while not stop_event.is_set():
        print(f"\r{Colors.CYAN}[{next(spinner)}]{Colors.RESET} {message}...", end="", flush=True)
        time.sleep(0.08)
    print(f"\r{' ' * (len(message) + 10)}\r", end="")

def thinking_animation(stop_event):
    """Show thinking animation."""
    dots = itertools.cycle(['', '.', '..', '...', '....', '.....'])
    while not stop_event.is_set():
        print(f"\r{Colors.DIM}[thinking{next(dots)}]{Colors.RESET}", end="", flush=True)
        time.sleep(0.3)
    print(f"\r{' ' * 20}\r", end="")

def banner():
    """Display terminal banner."""
    banner_text = f"""
{Colors.CYAN}    ██████╗ ██████╗  ██████╗ ███████╗███████╗███████╗ ██████╗ ██████╗     ████████╗██╗   ██╗██╗  ██╗
    ██╔══██╗██╔══██╗██╔═══██╗██╔════╝██╔════╝██╔════╝██╔═══██╗██╔══██╗    ╚══██╔══╝██║   ██║██║ ██╔╝
    ██████╔╝██████╔╝██║   ██║█████╗  █████╗  █████╗  ██║   ██║██████╔╝       ██║   ██║   ██║█████╔╝ 
    ██╔═══╝ ██╔══██╗██║   ██║██╔══╝  ██╔══╝  ██╔══╝  ██║   ██║██╔══██╗       ██║   ██║   ██║██╔═██╗ 
    ██║     ██║  ██║╚██████╔╝██║     ██║     ██║     ╚██████╔╝██║  ██║       ██║   ╚██████╔╝██║  ██╗
    ╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝     ╚═╝      ╚═════╝ ╚═╝  ╚═╝       ╚═╝    ╚═════╝ ╚═╝  ╚═╝
{Colors.GREEN}                          Cybersecurity Teaching Assistant v3.0
{Colors.DIM}                          Type 'exit' or 'quit' to logout{Colors.RESET}
"""
    print(banner_text)

def box_print(title, content, width=60):
    """Print content in a terminal box."""
    print(f"{Colors.CYAN}┌{'─' * (width - 2)}┐{Colors.RESET}")
    print(f"{Colors.CYAN}│{Colors.BOLD}{Colors.BRIGHT_GREEN} {title:<{width-3}}{Colors.RESET}{Colors.CYAN}│{Colors.RESET}")
    print(f"{Colors.CYAN}├{'─' * (width - 2)}┤{Colors.RESET}")
    for line in content.split('\n'):
        # Wrap long lines
        while len(line) > width - 4:
            segment = line[:width-4]
            print(f"{Colors.CYAN}│{Colors.RESET} {segment:<{width-4}}{Colors.CYAN}│{Colors.RESET}")
            line = line[width-4:]
        print(f"{Colors.CYAN}│{Colors.RESET} {line:<{width-4}}{Colors.CYAN}│{Colors.RESET}")
    print(f"{Colors.CYAN}└{'─' * (width - 2)}┘{Colors.RESET}")

def main():
    clear()
    banner()
    
    # Check server
    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=spinner_event, args=(stop_event, "Connecting to server"))
    spinner_thread.start()
    
    try:
        h = requests.get(f"{API}/health", timeout=5).json()
        stop_event.set()
        spinner_thread.join()
        
        if not h["model_loaded"]:
            print(f"{Colors.YELLOW}[!] No active model target is ready yet. Check Ollama or switch models from /admin.{Colors.RESET}\n")
            return
        
        print(f"{Colors.BRIGHT_GREEN}[✓] Connected | Modes: {', '.join(h['available_modes'])} | KB: {h['total_lecture_chunks']} chunks{Colors.RESET}\n")
    except Exception as e:
        stop_event.set()
        spinner_thread.join()
        print(f"{Colors.RED}[✗] Connection failed: Server offline{Colors.RESET}\n")
        return

    # Pick mode
    modes = requests.get(f"{API}/modes").json()["modes"]
    print(f"{Colors.CYAN}[*] Available teaching modes:{Colors.RESET}")
    for i, m in enumerate(modes):
        print(f"    {Colors.GREEN}[{i+1}]{Colors.RESET} {m['icon']} {Colors.BOLD}{m['name']}{Colors.RESET} — {m['description']}")

    print_prompt()
    choice = input().strip()
    idx = int(choice) - 1 if choice.isdigit() and 1 <= int(choice) <= len(modes) else 0
    mode = modes[idx]["id"]
    print(f"{Colors.DIM}> Selected: {modes[idx]['name']}{Colors.RESET}\n")

    print(f"{Colors.CYAN}[?] Topic (press Enter to skip):{Colors.RESET} ", end="")
    topic = input().strip() or None
    if topic:
        print(f"{Colors.DIM}> Focus: {topic}{Colors.RESET}\n")
    else:
        print()

    # Create session
    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=spinner_event, args=(stop_event, "Initializing session"))
    spinner_thread.start()
    
    sess = requests.post(f"{API}/sessions", json={
        "mode": mode, "topic": topic, "use_lectures": True
    }).json()
    
    stop_event.set()
    spinner_thread.join()

    # Welcome message
    box_print("SESSION INITIALIZED", sess["welcome_message"])
    print()

    # Chat loop
    while True:
        try:
            print_prompt("you", "cybersec-lab", "~/questions")
            msg = input().strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Colors.YELLOW}\n[!] Interrupted. Logging out...{Colors.RESET}")
            break
        
        if not msg: 
            continue
        if msg.lower() in ("quit", "exit", "q", "logout"): 
            print(f"{Colors.GREEN}[✓] Session terminated. Goodbye!{Colors.RESET}")
            break

        # Show thinking animation
        stop_event = threading.Event()
        think_thread = threading.Thread(target=thinking_animation, args=(stop_event,))
        think_thread.start()

        try:
            r = requests.post(f"{API}/chat", json={
                "session_id": sess["session_id"], "message": msg
            }).json()
            
            stop_event.set()
            think_thread.join()

            # Professor response
            print(f"\n{Colors.GREEN}┌──({Colors.CYAN}professor-tux@cybersec-lab{Colors.GREEN})-{Colors.MAGENTA}[AI]{Colors.RESET}")
            print(f"{Colors.GREEN}│{Colors.RESET}")
            for line in r['response'].split('\n'):
                print(f"{Colors.GREEN}│{Colors.RESET} {Colors.BRIGHT_GREEN}{line}{Colors.RESET}")
            print(f"{Colors.GREEN}│{Colors.RESET}")
            
            if r.get("sources_used"):
                sources = ', '.join(r['sources_used'])
                print(f"{Colors.GREEN}│{Colors.RESET} {Colors.DIM}📎 Sources: {sources}{Colors.RESET}")
            
            if r.get("hint"):
                print(f"{Colors.GREEN}│{Colors.RESET} {Colors.YELLOW}💡 {r['hint']}{Colors.RESET}")
            
            print(f"{Colors.GREEN}└─{Colors.RESET}\n")
            
            if r.get("mode") != mode:
                mode = r["mode"]
                print(f"{Colors.CYAN}[*] Mode switched to: {mode}{Colors.RESET}\n")
                
        except Exception as e:
            stop_event.set()
            think_thread.join()
            print(f"{Colors.RED}[✗] Error: {e}{Colors.RESET}\n")

if __name__ == "__main__":
    main()
