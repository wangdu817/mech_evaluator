from PIL import Image
from streamlit.testing.v1 import AppTest


def gallery_app(directory):
    from pyteck.respecth.ui_figures import render_saved_figures
    render_saved_figures(directory)


def test_all_images_default_and_optional_single_view(tmp_path):
    for name in ('set1', 'set2', 'set3'):
        Image.new('RGB', (1600, 800), 'white').save(tmp_path / f'{name}.png')
    at = AppTest.from_function(gallery_app, args=(str(tmp_path),), default_timeout=30).run()
    assert not at.exception
    assert len(at.image) == 3
    assert len(at.get('progress'))==1
    assert at.get('progress')[0].proto.value==100
    assert at.radio[0].value == '全部图表'
    at.number_input[0].set_value(2).run()
    assert len(at.image) == 3
    at.radio[0].set_value('单张查看').run()
    assert not at.exception
    assert len(at.image) == 1
    assert len(at.get('progress'))==0
    at.selectbox[0].select(tmp_path / 'set3.png').run()
    assert len(at.image) == 1
    assert at.selectbox[0].value.name == 'set3.png'
    at.radio[0].set_value('全部图表').run()
    assert len(at.image) == 3
    for preview in (tmp_path / '.previews').glob('*.png'):
        with Image.open(preview) as image:
            assert max(image.size) <= 1400


def test_one_bad_image_does_not_hide_remaining_figures(tmp_path):
    (tmp_path / 'bad.png').write_text('invalid image')
    Image.new('RGB', (20, 20), 'white').save(tmp_path / 'good.png')
    at = AppTest.from_function(gallery_app, args=(str(tmp_path),), default_timeout=30).run()
    assert not at.exception
    assert len(at.image) == 1
    assert 'bad.png' in at.warning[0].value

