"""Rename _id columns to id

Revision ID: 25c296b4a4cb
Revises: 49b76d8b3b3c
Create Date: 2025-04-06 13:00:17.530341

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25c296b4a4cb'
down_revision: Union[str, None] = '49b76d8b3b3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema using batch mode for SQLite compatibility."""

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('_id', new_column_name='id', existing_type=sa.TEXT(), nullable=False)
        batch_op.alter_column('created_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('updated_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('deleted_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=True)

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        batch_op.alter_column('_id', new_column_name='id', existing_type=sa.TEXT(), nullable=False)
        batch_op.alter_column('created_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('updated_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('deleted_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=True)
        batch_op.alter_column('last_activity_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=True)
        # Don't need to drop constraint in batch mode for clean DB
        # batch_op.drop_constraint('fk_conversations_created_by_user_id_users', type_='foreignkey')
        batch_op.create_foreign_key('fk_conversations_created_by_user_id_users', 'users', ['created_by_user_id'], ['id'])

    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('_id', new_column_name='id', existing_type=sa.TEXT(), nullable=False)
        batch_op.alter_column('created_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        # Don't need to drop constraints in batch mode for clean DB
        # batch_op.drop_constraint('fk_messages_conversation_id_conversations', type_='foreignkey')
        # batch_op.drop_constraint('fk_messages_created_by_user_id_users', type_='foreignkey')
        batch_op.create_foreign_key('fk_messages_conversation_id_conversations', 'conversations', ['conversation_id'], ['id'])
        batch_op.create_foreign_key('fk_messages_created_by_user_id_users', 'users', ['created_by_user_id'], ['id'])

    with op.batch_alter_table('participants', schema=None) as batch_op:
        batch_op.alter_column('_id', new_column_name='id', existing_type=sa.TEXT(), nullable=False)
        batch_op.alter_column('created_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('updated_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('joined_at', type_=sa.DateTime(timezone=True), existing_type=sa.TIMESTAMP(), nullable=True)
        # Don't need to drop constraints in batch mode for clean DB
        # batch_op.drop_constraint('fk_participants_user_id_users', type_='foreignkey')
        # batch_op.drop_constraint('fk_participants_conversation_id_conversations', type_='foreignkey')
        # batch_op.drop_constraint('fk_participants_invited_by_user_id_users', type_='foreignkey')
        # batch_op.drop_constraint('fk_participants_initial_message_id_messages', type_='foreignkey')
        batch_op.create_foreign_key('fk_participants_user_id_users', 'users', ['user_id'], ['id'])
        batch_op.create_foreign_key('fk_participants_conversation_id_conversations', 'conversations', ['conversation_id'], ['id'])
        batch_op.create_foreign_key('fk_participants_invited_by_user_id_users', 'users', ['invited_by_user_id'], ['id'])
        batch_op.create_foreign_key('fk_participants_initial_message_id_messages', 'messages', ['initial_message_id'], ['id'])


def downgrade() -> None:
    # Downgrade needs similar batch treatment, removing drops if not needed
    with op.batch_alter_table('participants', schema=None) as batch_op:
        # batch_op.drop_constraint('fk_participants_initial_message_id_messages', type_='foreignkey')
        # batch_op.drop_constraint('fk_participants_invited_by_user_id_users', type_='foreignkey')
        # batch_op.drop_constraint('fk_participants_conversation_id_conversations', type_='foreignkey')
        # batch_op.drop_constraint('fk_participants_user_id_users', type_='foreignkey')
        batch_op.create_foreign_key('fk_participants_initial_message_id_messages', 'messages', ['initial_message_id'], ['_id'])
        batch_op.create_foreign_key('fk_participants_invited_by_user_id_users', 'users', ['invited_by_user_id'], ['_id'])
        batch_op.create_foreign_key('fk_participants_conversation_id_conversations', 'conversations', ['conversation_id'], ['_id'])
        batch_op.create_foreign_key('fk_participants_user_id_users', 'users', ['user_id'], ['_id'])
        batch_op.alter_column('joined_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.alter_column('updated_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('created_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('id', new_column_name='_id', existing_type=sa.TEXT(), nullable=False)

    with op.batch_alter_table('messages', schema=None) as batch_op:
        # batch_op.drop_constraint('fk_messages_created_by_user_id_users', type_='foreignkey')
        # batch_op.drop_constraint('fk_messages_conversation_id_conversations', type_='foreignkey')
        batch_op.create_foreign_key('fk_messages_created_by_user_id_users', 'users', ['created_by_user_id'], ['_id'])
        batch_op.create_foreign_key('fk_messages_conversation_id_conversations', 'conversations', ['conversation_id'], ['_id'])
        batch_op.alter_column('created_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('id', new_column_name='_id', existing_type=sa.TEXT(), nullable=False)

    with op.batch_alter_table('conversations', schema=None) as batch_op:
        # batch_op.drop_constraint('fk_conversations_created_by_user_id_users', type_='foreignkey')
        batch_op.create_foreign_key('fk_conversations_created_by_user_id_users', 'users', ['created_by_user_id'], ['_id'])
        batch_op.alter_column('last_activity_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.alter_column('deleted_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.alter_column('updated_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('created_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('id', new_column_name='_id', existing_type=sa.TEXT(), nullable=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('deleted_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=True)
        batch_op.alter_column('updated_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('created_at', type_=sa.TIMESTAMP(), existing_type=sa.DateTime(timezone=True), nullable=False, existing_server_default=sa.text('(CURRENT_TIMESTAMP)'))
        batch_op.alter_column('id', new_column_name='_id', existing_type=sa.TEXT(), nullable=False)
