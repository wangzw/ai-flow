"""PyGithub wrapper with API parity to `gitlab_client.GitLabClient`.

Exposes the same method names so that handlers/coder/merge_queue can be
parameterized over either client without source changes.
"""
