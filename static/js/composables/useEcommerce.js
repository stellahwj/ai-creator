/**
 * E-commerce scene generation flow composable: 3-step state machine.
 */

import { ref } from 'vue';
import { authFetch } from '../api.js';

export function useEcommerce(form, currentTab, fetchJobs, fetchCredit, userValue) {
    const ecFlowState = ref('idle');
    const ecStep1Data = ref([]);
    const ecStep2Data = ref([]);
    const ecSettings = ref({ skip_step1_review: false, skip_step2_review: false, one_shot: false, scene_count: 3 });

    const isSubmitting = { value: false }; // will be linked externally

    let _setSubmitting = null;
    const linkSubmitting = (setFn) => { _setSubmitting = setFn; };
    const setSubmitting = (v) => { if (_setSubmitting) _setSubmitting(v); };

    const cancelEcommerceFlow = () => {
        ecFlowState.value = 'idle';
        setSubmitting(false);
    };

    const runEcommerceJobSubmit = async () => {
        ecFlowState.value = 'job_submitting';
        try {
            const ecData = ecStep2Data.value
                .map(item => ({ image_path: item.image_path, scenes: (item.scenes || []).filter(s => s.trim()) }))
                .filter(item => item.scenes.length > 0);
            if (!ecData.length) throw new Error('No valid scenes — please keep at least one scene.');

            const fd = new FormData();
            fd.append('mode', 'ecommerce');
            fd.append('model_id', form.value.model_id);
            fd.append('target_ratio', form.value.target_ratio || '1:1');
            fd.append('batch_size', 1);
            fd.append('ecommerce_data', JSON.stringify(ecData));
            fd.append('prompts', '');
            fd.append('negative_prompt', form.value.negative_prompt || '');
            fd.append('template_name', '');

            const res = await authFetch('/api/jobs', { method: 'POST', body: fd });
            const data = await res.json();
            if (!res.ok || !data.id) throw new Error(data.error || 'Failed to submit job');

            ecFlowState.value = 'idle';
            setSubmitting(false);
            form.value.files = [];
            currentTab.value = 'jobs';
            fetchJobs(userValue());
            fetchCredit();
        } catch (e) {
            alert('Failed to submit job: ' + e.message);
            cancelEcommerceFlow();
        }
    };

    const runEcommerceStep2 = async () => {
        ecFlowState.value = 'step2_loading';
        try {
            const res = await authFetch('/api/ecommerce/scenes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    items: ecStep1Data.value.map(item => ({
                        image_path: item.image_path,
                        image_name: item.image_name,
                        display_url: item.display_url,
                        description: item.description,
                    })),
                    scene_count: ecSettings.value.scene_count,
                }),
            });
            if (!res.ok) { const d = await res.json(); throw new Error(d.error || 'AI scene generation failed'); }
            const data = await res.json();
            ecStep2Data.value = data.items;
            if (ecSettings.value.one_shot || ecSettings.value.skip_step2_review) {
                await runEcommerceJobSubmit();
            } else {
                ecFlowState.value = 'step2_review';
                setSubmitting(false);
            }
        } catch (e) {
            alert('Scene generation failed: ' + e.message);
            cancelEcommerceFlow();
        }
    };

    const proceedToStep2 = async () => {
        setSubmitting(true);
        await runEcommerceStep2();
    };

    const backToStep1 = () => { ecFlowState.value = 'step1_review'; };

    const proceedToSubmit = async () => {
        setSubmitting(true);
        await runEcommerceJobSubmit();
    };

    const startEcommerceFlow = async () => {
        if (form.value.files.length === 0) { alert('Please upload at least one product image.'); return; }
        setSubmitting(true);
        ecFlowState.value = 'step1_loading';
        try {
            const fd = new FormData();
            form.value.files.forEach(f => fd.append('images', f));
            const res = await authFetch('/api/ecommerce/understand', { method: 'POST', body: fd });
            if (!res.ok) { const d = await res.json(); throw new Error(d.error || 'AI product analysis failed'); }
            const data = await res.json();
            ecStep1Data.value = data.items;
            if (ecSettings.value.one_shot || ecSettings.value.skip_step1_review) {
                await runEcommerceStep2();
            } else {
                ecFlowState.value = 'step1_review';
                setSubmitting(false);
            }
        } catch (e) {
            alert('Product analysis failed: ' + e.message);
            cancelEcommerceFlow();
        }
    };

    const fetchSettings = async () => {
        try {
            const res = await authFetch('/api/settings');
            if (res.ok) {
                const data = await res.json();
                if (data.ecommerce) Object.assign(ecSettings.value, data.ecommerce);
            }
        } catch (e) {}
    };

    const saveEcSettings = async () => {
        try {
            await authFetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ecommerce: { ...ecSettings.value } }),
            });
        } catch (e) {}
    };

    return {
        ecFlowState, ecStep1Data, ecStep2Data, ecSettings,
        cancelEcommerceFlow, proceedToStep2, proceedToSubmit, backToStep1,
        startEcommerceFlow, fetchSettings, saveEcSettings, linkSubmitting,
    };
}
