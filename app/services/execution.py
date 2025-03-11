import docker
import uuid
import logging
import os
import shlex
import asyncio
from datetime import datetime
import shutil

from app.core.config import settings

logger = logging.getLogger(__name__)


class CodeExecutionService:
    def __init__(self):
        # Check if we should use Docker based on environment variable
        self.use_docker = settings.USE_DOCKER
        self.client = None
        self.active_containers = {}
        self.active_sessions = {}
        self.workspace_root = settings.WORKSPACE_ROOT

        # Only initialize Docker client if we're using Docker
        if self.use_docker:
            try:
                self.client = docker.from_env()
                logger.info("Docker client initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Docker client: {e}")
                self.use_docker = False

    async def create_session(self, language):
        """Create a new code execution session with interactive terminal"""
        session_id = str(uuid.uuid4())

        if self.use_docker:
            # Docker-based execution
            return await self._create_docker_session(session_id, language)
        else:
            # Fallback: Process-based execution
            return await self._create_process_session(session_id, language)

    async def _create_docker_session(self, session_id, language):
        """Create a Docker-based execution session"""
        if language not in settings.LANGUAGE_IMAGES:
            raise ValueError(f"Unsupported language: {language}")

        image_name = settings.LANGUAGE_IMAGES[language]

        # The container will see the same directory at:
        container_workspace = f"{settings.WORKSPACE_ROOT}"

        logger.info(f"Container workspace path: {container_workspace}")

        try:
            container = self.client.containers.run(
                image=image_name,
                detach=True,
                tty=True,
                stdin_open=True,
                volumes={
                    container_workspace: {
                        'bind': '/code',
                        'mode': 'rw'
                    }
                },
                working_dir='/code',
                # Resource limits
                mem_limit='256m',
                cpu_period=100000,
                cpu_quota=20000,  # 20% of CPU
                # Security settings
                cap_drop=['ALL'],
                security_opt=['no-new-privileges:true'],
                network_mode='none'
            )

            # Verify volume mounting worked
            exit_code, output = container.exec_run(f"ls -la {container_workspace}")
            logger.info(
                f"Initial container workspace: {output.decode('utf-8')}")

            # Store container information
            self.active_containers[session_id] = {
                'container': container,
                'language': language,
                'created_at': datetime.now()
            }

            logger.info(
                f"Created Docker session {session_id} for language {language}")
            return session_id

        except Exception as e:
            # Clean up workspace if creation failed
            if os.path.exists(container_workspace):
                shutil.rmtree(container_workspace)
            logger.error(f"Failed to create Docker session: {e}")
            raise ValueError(f"Failed to create Docker session: {str(e)}")

    async def _create_process_session(self, session_id, language):
        """Create a process-based execution session (fallback)"""
        # Create workspace directory for this session
        workspace_path = f"{self.workspace_root}/{session_id}"
        os.makedirs(workspace_path, exist_ok=True)

        # Store session information
        self.active_sessions[session_id] = {
            'language': language,
            'created_at': datetime.now(),
            'workspace_path': workspace_path
        }

        logger.info(
            f"Created process-based session {session_id} for language {language}")
        return session_id

    async def execute_code(self, session_id, code, input_data=None, timeout=None):
        """Execute code in an existing session"""
        if timeout is None:
            timeout = settings.MAX_EXECUTION_TIME

        if session_id not in self.active_containers and session_id not in self.active_sessions:
            raise ValueError(f"Session {session_id} not found")

        if self.use_docker and session_id in self.active_containers:
            container_info = self.active_containers[session_id]
            language = container_info['language']
            container = container_info['container']

            # Use a common host directory (instead of a subdirectory based on the session id)
            code_dir = "./workspace"
            os.makedirs(code_dir, exist_ok=True)
            file_ext = settings.FILE_EXTENSIONS.get(language, 'txt')
            unique_filename = f"code_{uuid.uuid4().hex}.{file_ext}"
            code_path = os.path.join(code_dir, unique_filename)
            logger.debug(f"Writing code file at: {code_path}")

            with open(code_path, "w") as f:
                f.write(code)

            logger.info(f"Successfully wrote code file to: {os.path.abspath(code_path)}")

            # Write input data to a temporary file if provided
            if input_data:
                input_filename = f"input_{uuid.uuid4().hex}.txt"
                input_path = os.path.join(code_dir, input_filename)
                with open(input_path, "w") as f:
                    f.write(input_data)
                logger.info(f"Successfully wrote input file to: {os.path.abspath(input_path)}")
            else:
                input_filename = None

            if not os.path.exists(code_path):
                logger.error(f"Code file not created at: {code_path}")
                raise RuntimeError("Failed to create code file")


            # Prepare the command based on language
            if language == 'python':
                if input_data:
                    cmd = f"bash -c 'python /code/{unique_filename} < /code/{input_filename}'"
                else:
                    cmd = f"python /code/{unique_filename}"

            elif language == 'cpp':
                compile_cmd = f"g++ /code/{unique_filename} -o /code/a.out"
                if input_data:
                    escaped_input = shlex.quote(input_data or '')
                    run_cmd = f"echo {escaped_input} | /code/a.out"
                else:
                    run_cmd = f"/code/a.out"
                cmd = f"sh -c '{compile_cmd} && {run_cmd}'"

            elif language == 'java':
                class_name = "Main"
                if input_data:
                    cmd = f"bash -c 'javac /code/{unique_filename} && java -cp /code {class_name} < /code/{input_filename}'"
                else:
                    cmd = f"bash -c 'javac /code/{unique_filename} && java -cp /code {class_name}'"

            elif language == 'javascript':
                if input_data:
                    cmd = f"bash -c 'node /code/{unique_filename} < /code/{input_filename}'"
                else:
                    cmd = f"node /code/{unique_filename}"
            else:
                cmd = f"cat /code/{unique_filename}"


            logger.debug(f"Executing command in container: {cmd}")

            # Execute in container with timeout
            try:
                exit_code, output = container.exec_run(
                    cmd=cmd,
                    tty=True,
                    demux=True,  # Split stdout and stderr
                )

                # Process output
                stdout = output[0].decode('utf-8') if output[0] else ""
                stderr = output[1].decode('utf-8') if output[1] else ""

                # Clean up temporary files after execution
                # os.remove(code_path)
                # if input_filename:
                #     os.remove(input_path)

                return {
                    'exit_code': exit_code,
                    'output': stdout,
                    'error': stderr if stderr else None
                }
            except Exception as e:
                return {
                    'exit_code': 1,
                    'output': "",
                    'error': str(e)
                }
        else:
            # Process-based execution (fallback)
            return await self._execute_in_process(session_id, code, input_data, timeout)

    async def _execute_in_process(self, session_id, code, input_data=None, timeout=10):
        """Execute code using a subprocess (fallback method)"""
        session_info = self.active_sessions[session_id]
        language = session_info['language']
        workspace_path = session_info['workspace_path']

        # Create code file
        file_ext = settings.FILE_EXTENSIONS.get(language, 'txt')
        code_path = f"{workspace_path}/code.{file_ext}"

        with open(code_path, "w") as f:
            f.write(code)

        # Create temporary input file if needed
        input_path = None
        if input_data:
            input_path = f"{workspace_path}/input.txt"
            with open(input_path, "w") as f:
                f.write(input_data)

        # Prepare the command based on language
        if language == 'python':
            cmd = ["python", code_path]
        elif language == 'javascript':
            cmd = ["node", code_path]
        else:
            # Fallback for unsupported languages in process mode
            return {
                'exit_code': 1,
                'output': "",
                'error': f"Language {language} not supported in process mode"
            }

        # Execute the code
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if input_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Set up timeout
            try:
                if input_data:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(input=input_data.encode()),
                        timeout=timeout
                    )
                else:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=timeout
                    )

                return {
                    'exit_code': process.returncode,
                    'output': stdout.decode(),
                    'error': stderr.decode() if stderr else None
                }
            except asyncio.TimeoutError:
                # Kill the process if it times out
                process.kill()
                return {
                    'exit_code': 1,
                    'output': "",
                    'error': f"Execution timed out after {timeout} seconds"
                }

        except Exception as e:
            return {
                'exit_code': 1,
                'output': "",
                'error': str(e)
            }

    async def execute_code_with_streaming(self, session_id, code, input_data=None, timeout=None, callback=None):
        """Execute code with streaming output via callback"""
        if timeout is None:
            timeout = settings.MAX_EXECUTION_TIME

        if session_id not in self.active_containers and session_id not in self.active_sessions:
            raise ValueError(f"Session {session_id} not found")

        # For now, just execute and send the complete result through callback
        result = await self.execute_code(session_id, code, input_data, timeout)

        if callback:
            await callback({
                'output': result['output'],
                'error': result['error'],
                'exit_code': result['exit_code'],
                'complete': True
            })

        return result

    async def terminate_session(self, session_id):
        """Terminate an execution session and clean up resources"""
        if session_id in self.active_containers:
            # Docker-based session
            try:
                container_info = self.active_containers[session_id]
                container = container_info['container']

                # Stop and remove the container
                container.stop(timeout=2)
                container.remove(force=True)

                # Remove session from active containers
                del self.active_containers[session_id]

                # Clean up workspace
                workspace_path = f"{self.workspace_root}/{session_id}"
                if os.path.exists(workspace_path):
                    shutil.rmtree(workspace_path)

                logger.info(f"Terminated Docker session {session_id}")
                return True
            except Exception as e:
                logger.error(
                    f"Error terminating Docker session {session_id}: {e}")
                return False
        elif session_id in self.active_sessions:
            # Process-based session
            try:
                # Clean up workspace
                workspace_path = self.active_sessions[session_id]['workspace_path']
                if os.path.exists(workspace_path):
                    shutil.rmtree(workspace_path)

                # Remove session
                del self.active_sessions[session_id]

                logger.info(f"Terminated process session {session_id}")
                return True
            except Exception as e:
                logger.error(
                    f"Error terminating process session {session_id}: {e}")
                return False
        else:
            logger.warning(f"Session {session_id} not found for termination")
            return False


# Create a singleton instance
execution_service = CodeExecutionService()
