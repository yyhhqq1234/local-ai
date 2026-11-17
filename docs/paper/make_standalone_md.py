import os
import base64
import re

def convert_md_to_standalone(md_path, out_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    def replace_img(match):
        rel_path = match.group(1)
        clean_path = rel_path.replace('/', os.sep)
        full_path = os.path.join(os.path.dirname(md_path), clean_path)
        if os.path.exists(full_path):
            with open(full_path, 'rb') as img_f:
                b64 = base64.b64encode(img_f.read()).decode('utf-8')
            return f'<img src="data:image/png;base64,{b64}"'
        else:
            print(f"Warning: {full_path} not found!")
            return match.group(0)

    new_content = re.sub(r'<img\s+src="([^"]+)"', replace_img, content)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Generated: {out_path} ({os.path.getsize(out_path)} bytes)")

def verify_standalone(path):
    with open(path, 'r', encoding='utf-8') as f:
        txt = f.read()
    b64_imgs = re.findall(r'<img\s+src="data:image/png;base64,[^"]+"', txt)
    rel_imgs = re.findall(r'<img\s+src="images/[^"]+"', txt)
    print(f"{path}: base64 images = {len(b64_imgs)}, relative images = {len(rel_imgs)}")
    forbidden = ['石井', 'Ishii', '2024YFB', '624XXXX', '系统软件与智能安全实验室']
    for fb in forbidden:
        assert fb not in txt, f"Found forbidden: {fb}"
    assert len(b64_imgs) == 8, f"Expected 8 b64 images, got {len(b64_imgs)}"
    assert len(rel_imgs) == 0, f"Expected 0 relative images, got {len(rel_imgs)}"
    print(f"[PASS] {path} is fully self-contained and clean.")

if __name__ == '__main__':
    convert_md_to_standalone('docs/paper/beyond_surface_adaptation_zh.md', 'docs/paper/beyond_surface_adaptation_zh_standalone.md')
    convert_md_to_standalone('docs/paper/beyond_surface_adaptation.md', 'docs/paper/beyond_surface_adaptation_standalone.md')
    verify_standalone('docs/paper/beyond_surface_adaptation_zh_standalone.md')
    verify_standalone('docs/paper/beyond_surface_adaptation_standalone.md')
