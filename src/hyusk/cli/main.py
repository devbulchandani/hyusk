"""Main CLI interface for Hyusk."""

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hyusk import __version__
from hyusk.config import get_config
from hyusk.database import get_database
from hyusk.logging import get_logger, setup_logging

console = Console()
logger = get_logger(__name__)


@click.group()
@click.version_option(version=__version__, prog_name="hyusk")
@click.option("--debug", is_flag=True, help="Enable debug mode")
def cli(debug: bool) -> None:
    """Hyusk - Your personal AI operating layer."""
    if debug:
        config = get_config()
        config.debug = True


@cli.command()
def init() -> None:
    """Initialize Hyusk (create directories and database)."""
    console.print("[bold blue]Initializing Hyusk...[/bold blue]")

    try:
        # Setup logging
        setup_logging()

        # Load config and ensure directories
        config = get_config()
        config.ensure_directories()
        console.print("✓ Created required directories")

        # Initialize database
        async def _init_db() -> None:
            db = get_database()
            await db.init_db()

        asyncio.run(_init_db())
        console.print("✓ Initialized database")

        console.print("\n[bold green]✓ Hyusk initialized successfully![/bold green]")
        console.print("\nNext steps:")
        console.print("1. Copy .env.example to .env and configure your API keys")
        console.print("2. Run 'hyusk doctor' to verify your setup")
        console.print("3. Run 'hyusk chat' to start chatting")

    except Exception as e:
        console.print(f"[bold red]✗ Initialization failed:[/bold red] {e}")
        logger.exception("Initialization failed")
        sys.exit(1)


@cli.command()
def doctor() -> None:
    """Check system requirements and configuration."""
    console.print(Panel.fit("[bold]Hyusk System Diagnostics[/bold]", border_style="blue"))

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Component", style="dim", width=20)
    table.add_column("Status", width=10)
    table.add_column("Details")

    try:
        # Python version
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if sys.version_info >= (3, 12):
            table.add_row("Python", "✓", f"Version {py_version}")
        else:
            table.add_row("Python", "✗", f"Version {py_version} (requires 3.12+)")

        # Configuration
        try:
            config = get_config()
            table.add_row("Configuration", "✓", "Loaded successfully")

            # Check directories
            hyusk_dir = Path(config.hyusk_dir).expanduser()
            if hyusk_dir.exists():
                table.add_row("Hyusk Directory", "✓", str(hyusk_dir))
            else:
                table.add_row("Hyusk Directory", "⚠", f"{hyusk_dir} (not created)")

            # Check LLM configuration
            if config.llm.anthropic_api_key or config.llm.openai_api_key:
                provider = config.llm.default_provider
                table.add_row("LLM Provider", "✓", f"{provider.capitalize()} configured")
            else:
                table.add_row("LLM Provider", "✗", "No API keys configured")

            # Voice
            if config.voice.enabled:
                table.add_row("Voice", "○", "Enabled but not yet implemented")
            else:
                table.add_row("Voice", "○", "Disabled")

            # Database
            async def _check_db() -> bool:
                try:
                    db = get_database()
                    async with db.get_session() as session:
                        # Try a simple query
                        await session.execute("SELECT 1")
                    return True
                except Exception:
                    return False

            db_ok = asyncio.run(_check_db())
            if db_ok:
                table.add_row("Database", "✓", "Connected")
            else:
                table.add_row("Database", "⚠", "Not initialized (run 'hyusk init')")

            # Remote API
            if config.remote.enabled:
                table.add_row(
                    "Remote API", "○", f"Configured on {config.remote.host}:{config.remote.port}"
                )
            else:
                table.add_row("Remote API", "○", "Disabled")

        except Exception as e:
            table.add_row("Configuration", "✗", str(e))

        # Platform
        import platform

        system = platform.system()
        table.add_row("Platform", "✓" if system == "Darwin" else "⚠", system)

    except Exception as e:
        console.print(f"[bold red]Error running diagnostics:[/bold red] {e}")
        sys.exit(1)

    console.print(table)
    console.print("\n[dim]Legend: ✓ OK  ⚠ Warning  ✗ Error  ○ Optional[/dim]")


@cli.command()
@click.option("--model", default="default", help="Model type to use (default, fast, coding)")
@click.option("--stream/--no-stream", default=True, help="Enable streaming responses")
def chat(model: str, stream: bool) -> None:
    """Start an interactive chat session."""
    from uuid import uuid4

    from hyusk.core.orchestrator import get_orchestrator

    console.print(Panel.fit("[bold cyan]Hyusk Interactive Chat[/bold cyan]", border_style="cyan"))
    console.print("[dim]Type 'exit' or 'quit' to end the session[/dim]\n")

    # Check if LLM is configured
    try:
        config = get_config()
        if not config.llm.anthropic_api_key and not config.llm.openai_api_key:
            console.print("[bold red]✗ No LLM API keys configured[/bold red]")
            console.print("\nPlease set API keys in .env:")
            console.print("  ANTHROPIC_API_KEY=your_key_here")
            console.print("  OR")
            console.print("  OPENAI_API_KEY=your_key_here")
            sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Configuration error:[/bold red] {e}")
        sys.exit(1)

    # Setup logging
    setup_logging()

    # Load default tools
    from hyusk.tools.loader import load_default_tools

    load_default_tools()

    # Create conversation
    conversation_id = uuid4()
    orchestrator = get_orchestrator()

    # Get tool schemas for LLM
    from hyusk.tools.registry import get_registry

    tool_schemas = get_registry().get_tool_schemas()

    console.print(f"[dim]Using model type: {model}[/dim]")
    console.print(f"[dim]Streaming: {'enabled' if stream else 'disabled'}[/dim]")
    console.print(f"[dim]Tools available: {len(tool_schemas)}[/dim]\n")

    async def run_chat() -> None:
        """Run the chat loop."""
        while True:
            try:
                # Get user input
                user_input = console.input("[bold green]You:[/bold green] ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ["exit", "quit", "bye"]:
                    console.print("\n[dim]Goodbye![/dim]")
                    break

                # Get response
                console.print("[bold blue]Hyusk:[/bold blue] ", end="")

                if stream:
                    # Streaming response
                    full_response = []
                    tool_calls_made = []
                    async for chunk in orchestrator.stream_request(
                        user_message=user_input,
                        conversation_id=conversation_id,
                        model_type=model,
                        tools=tool_schemas,
                    ):
                        if chunk.content:
                            console.print(chunk.content, end="")
                            full_response.append(chunk.content)

                        if chunk.tool_call:
                            tool_calls_made.append(chunk.tool_call)
                            console.print(
                                f"\n[dim]→ Calling tool: {chunk.tool_call.tool_name}[/dim]"
                            )

                    # If tools were called, get final response with handle_request
                    if tool_calls_made and not full_response:
                        console.print("[dim]→ Executing tools...[/dim]\n")
                        console.print("[bold blue]Hyusk:[/bold blue] ", end="")
                        response = await orchestrator.handle_request(
                            user_message=user_input,
                            conversation_id=conversation_id,
                            model_type=model,
                            tools=tool_schemas,
                        )
                        if response.content:
                            console.print(response.content)

                    console.print("\n")
                else:
                    # Non-streaming response
                    response = await orchestrator.handle_request(
                        user_message=user_input,
                        conversation_id=conversation_id,
                        model_type=model,
                        tools=tool_schemas,
                    )

                    if response.content:
                        console.print(response.content)
                    else:
                        console.print("[dim](no response)[/dim]")

                    console.print()

            except KeyboardInterrupt:
                console.print("\n\n[dim]Interrupted. Type 'exit' to quit.[/dim]\n")
                continue
            except Exception as e:
                console.print(f"\n[bold red]Error:[/bold red] {e}\n")
                logger.exception("Chat error")

    # Run the async chat loop
    asyncio.run(run_chat())


@cli.command()
@click.option("--no-wake-word", is_flag=True, help="Skip wake word, start listening immediately")
@click.option("--model", default="default", help="Model type to use")
def voice(no_wake_word: bool, model: str) -> None:
    """Start voice interaction mode."""
    from uuid import uuid4

    from hyusk.core.orchestrator import get_orchestrator
    from hyusk.voice.audio import AudioConfig, AudioInput, AudioOutput
    from hyusk.voice.stt import WhisperSTT
    from hyusk.voice.tts import SystemTTS
    from hyusk.voice.wakeword import SimpleWakeWord

    # Check configuration
    config = get_config()
    
    if not config.voice.enabled:
        console.print("[yellow]⚠ Voice is disabled in configuration[/yellow]")
        console.print("[dim]Set VOICE_ENABLED=true in .env to enable[/dim]\n")
    
    if not config.llm.anthropic_api_key and not config.llm.openai_api_key:
        console.print("[bold red]✗ No LLM API keys configured[/bold red]")
        sys.exit(1)

    console.print(Panel.fit("[bold magenta]Hyusk Voice Mode[/bold magenta]", border_style="magenta"))
    console.print("[dim]Press Ctrl+C to exit[/dim]\n")

    # Setup
    setup_logging()
    
    from hyusk.tools.loader import load_default_tools
    load_default_tools()

    conversation_id = uuid4()
    orchestrator = get_orchestrator()

    from hyusk.tools.registry import get_registry
    tool_schemas = get_registry().get_tool_schemas()

    async def run_voice() -> None:
        """Run voice interaction loop."""
        # Initialize voice components
        audio_config = AudioConfig(
            sample_rate=16000,
            language=config.voice.stt_language,
            model_size=config.voice.stt_model,
            voice=config.voice.tts_voice,
            speed=config.voice.tts_speed,
            wake_phrase=config.voice.wake_word,
        )

        stt = WhisperSTT(audio_config)
        tts = SystemTTS(audio_config)  # Use system TTS for simplicity
        audio_input = AudioInput(audio_config)
        audio_output = AudioOutput(audio_config)

        try:
            console.print("[cyan]Initializing voice components...[/cyan]")
            await stt.initialize()
            await tts.initialize()
            await audio_input.initialize()
            await audio_output.initialize()
            console.print("[green]✓ Voice components ready[/green]\n")

            if not no_wake_word:
                wake_word = SimpleWakeWord(audio_config)
                await wake_word.initialize()
                console.print(f"[yellow]Say '{config.voice.wake_word}' to start[/yellow]\n")

            while True:
                try:
                    # Wait for wake word
                    if not no_wake_word:
                        console.print("[dim]Listening for wake word...[/dim]")
                        detected = await wake_word.wait_for_wake_word(timeout=5.0)
                        if not detected:
                            continue
                        console.print("[green]Wake word detected![/green]")

                    # Record user speech
                    console.print("[cyan]Listening... (3 seconds)[/cyan]")
                    audio_data = await audio_input.record(3.0)

                    # Transcribe
                    console.print("[cyan]Transcribing...[/cyan]")
                    user_text = await stt.transcribe(audio_data)
                    
                    if not user_text or len(user_text.strip()) < 2:
                        console.print("[dim]No speech detected[/dim]\n")
                        continue

                    console.print(f"[bold green]You:[/bold green] {user_text}\n")

                    # Check for exit commands
                    if user_text.lower().strip() in ["exit", "quit", "stop", "goodbye"]:
                        await tts.speak("Goodbye!")
                        console.print("[dim]Goodbye![/dim]")
                        break

                    # Get LLM response
                    console.print("[cyan]Thinking...[/cyan]")
                    response = await orchestrator.handle_request(
                        user_message=user_text,
                        conversation_id=conversation_id,
                        model_type=model,
                        tools=tool_schemas,
                    )

                    response_text = response.content or "I'm not sure what to say."
                    console.print(f"[bold blue]Hyusk:[/bold blue] {response_text}\n")

                    # Speak response
                    console.print("[cyan]Speaking...[/cyan]")
                    await tts.speak(response_text)
                    console.print()

                except KeyboardInterrupt:
                    console.print("\n[yellow]Interrupted[/yellow]")
                    break
                except Exception as e:
                    console.print(f"[bold red]Error:[/bold red] {e}\n")
                    logger.exception("Voice interaction error")
                    continue

        finally:
            # Cleanup
            console.print("\n[cyan]Cleaning up...[/cyan]")
            await stt.cleanup()
            await tts.cleanup()
            await audio_input.cleanup()
            await audio_output.cleanup()
            if not no_wake_word:
                await wake_word.cleanup()
            console.print("[green]✓ Cleanup complete[/green]")

    try:
        asyncio.run(run_voice())
    except KeyboardInterrupt:
        console.print("\n[dim]Voice mode stopped[/dim]")
    except Exception as e:
        console.print(f"[bold red]Voice mode failed:[/bold red] {e}")
        logger.exception("Voice mode error")
        sys.exit(1)


@cli.group()
def task() -> None:
    """Manage tasks."""
    pass


@task.command(name="list")
def task_list() -> None:
    """List all tasks."""
    console.print("[bold red]Task management not yet implemented[/bold red]")
    console.print("This feature is coming in Phase 8 (Tasks)")


@task.command(name="status")
@click.argument("task_id")
def task_status(task_id: str) -> None:
    """Show task status."""
    console.print("[bold red]Task management not yet implemented[/bold red]")


@task.command(name="stop")
@click.argument("task_id")
def task_stop(task_id: str) -> None:
    """Stop a running task."""
    console.print("[bold red]Task management not yet implemented[/bold red]")


@cli.group()
def agent() -> None:
    """Manage agents."""
    pass


@agent.command(name="list")
def agent_list() -> None:
    """List all agents."""
    console.print("[bold red]Agent management not yet implemented[/bold red]")
    console.print("This feature is coming in Phase 9 (Agents)")


@agent.command(name="status")
@click.argument("agent_id")
def agent_status(agent_id: str) -> None:
    """Show agent status."""
    console.print("[bold red]Agent management not yet implemented[/bold red]")


@agent.command(name="stop")
@click.argument("agent_id")
def agent_stop(agent_id: str) -> None:
    """Stop a running agent."""
    console.print("[bold red]Agent management not yet implemented[/bold red]")


@cli.group()
def approvals() -> None:
    """Manage permission approvals."""
    pass


@approvals.command(name="list")
def approvals_list() -> None:
    """List pending approvals."""
    import asyncio

    from hyusk.permissions.engine import get_engine

    async def _list() -> None:
        engine = get_engine()
        pending = await engine.list_pending_requests()

        if not pending:
            console.print("[dim]No pending approval requests[/dim]")
            return

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID", style="dim")
        table.add_column("Tool")
        table.add_column("Arguments", max_width=40)
        table.add_column("Reason", max_width=50)
        table.add_column("Created", style="dim")
        table.add_column("Expires", style="dim")

        for request in pending:
            args_str = str(request.arguments)
            if len(args_str) > 40:
                args_str = args_str[:37] + "..."

            reason_str = request.reason
            if len(reason_str) > 50:
                reason_str = reason_str[:47] + "..."

            # Format timestamps
            created = request.created_at.strftime("%H:%M:%S")
            expires = request.expires_at.strftime("%H:%M:%S")

            table.add_row(
                str(request.id)[:8],
                request.tool,
                args_str,
                reason_str,
                created,
                expires,
            )

        console.print(table)
        console.print(
            f"\n[dim]Use 'hyusk approve <id>' or 'hyusk reject <id>' to respond[/dim]"
        )

    asyncio.run(_list())


@approvals.command(name="approve")
@click.argument("approval_id")
def approve(approval_id: str) -> None:
    """Approve a permission request."""
    import asyncio
    from uuid import UUID

    from hyusk.permissions.engine import get_engine

    async def _approve() -> None:
        try:
            request_id = UUID(approval_id)
            engine = get_engine()
            decision = await engine.approve_request(request_id, reason="Approved via CLI")

            console.print(f"[bold green]✓ Approval {approval_id[:8]} approved[/bold green]")
            console.print(f"[dim]{decision.reason}[/dim]")
        except ValueError as e:
            console.print(f"[bold red]✗ Error:[/bold red] {e}")
            sys.exit(1)
        except Exception as e:
            console.print(f"[bold red]✗ Unexpected error:[/bold red] {e}")
            sys.exit(1)

    asyncio.run(_approve())


@approvals.command(name="reject")
@click.argument("approval_id")
def reject(approval_id: str) -> None:
    """Reject a permission request."""
    import asyncio
    from uuid import UUID

    from hyusk.permissions.engine import get_engine

    async def _reject() -> None:
        try:
            request_id = UUID(approval_id)
            engine = get_engine()
            decision = await engine.reject_request(request_id, reason="Rejected via CLI")

            console.print(f"[bold yellow]✗ Approval {approval_id[:8]} rejected[/bold yellow]")
            console.print(f"[dim]{decision.reason}[/dim]")
        except ValueError as e:
            console.print(f"[bold red]✗ Error:[/bold red] {e}")
            sys.exit(1)
        except Exception as e:
            console.print(f"[bold red]✗ Unexpected error:[/bold red] {e}")
            sys.exit(1)

    asyncio.run(_reject())


@cli.group()
def daemon() -> None:
    """Control the Hyusk daemon."""
    pass


@daemon.command(name="start")
def daemon_start() -> None:
    """Start the Hyusk daemon."""
    console.print("[bold red]Daemon not yet implemented[/bold red]")
    console.print("This feature is coming in a future phase")


@daemon.command(name="stop")
def daemon_stop() -> None:
    """Stop the Hyusk daemon."""
    console.print("[bold red]Daemon not yet implemented[/bold red]")


@daemon.command(name="status")
def daemon_status() -> None:
    """Show daemon status."""
    console.print("[bold red]Daemon not yet implemented[/bold red]")


@cli.command()
def config() -> None:
    """Show current configuration."""
    try:
        cfg = get_config()
        config_path = Path(cfg.config_file).expanduser()

        console.print(f"[bold]Configuration File:[/bold] {config_path}")

        if config_path.exists():
            console.print("\n[dim]To edit configuration, modify the YAML file directly[/dim]")
        else:
            console.print("\n[yellow]Configuration file not found. Using defaults.[/yellow]")

        # Show key settings
        console.print("\n[bold]Current Settings:[/bold]")
        console.print(f"  LLM Provider: {cfg.llm.default_provider}")
        console.print(f"  Default Model: {cfg.llm.default_model}")
        console.print(f"  Voice: {'Enabled' if cfg.voice.enabled else 'Disabled'}")
        console.print(f"  Remote API: {'Enabled' if cfg.remote.enabled else 'Disabled'}")
        console.print(f"  Debug: {'Enabled' if cfg.debug else 'Disabled'}")

    except Exception as e:
        console.print(f"[bold red]Error loading configuration:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
