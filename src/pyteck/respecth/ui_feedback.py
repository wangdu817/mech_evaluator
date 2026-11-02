"""One persistent action receipt plus a toast, without polling or history growth."""
import streamlit as st


def show_action_notice():
    slot = st.empty()
    message = st.session_state.get('action_notice')
    if message:
        slot.success(message)
    pending = st.session_state.pop('action_notice_toast', None)
    if pending:
        st.toast(pending, icon='✅')
    return slot


def action_success(message, slot=None):
    st.session_state['action_notice'] = message
    if slot is None:
        # The caller reruns after changing widget values. Deliver the toast then.
        st.session_state['action_notice_toast'] = message
    else:
        slot.success(message)
        st.toast(message, icon='✅')


def clear_action_notice(slot=None):
    st.session_state.pop('action_notice', None)
    st.session_state.pop('action_notice_toast', None)
    if slot is not None:
        slot.empty()
