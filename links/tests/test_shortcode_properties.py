"""
Property-based tests for short code generation and validation.

Feature: url-shortener
Uses hypothesis library for property-based testing.
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
import string

from links.services import ShortCodeGenerator, BASE62_CHARS, short_code_generator


# Strategies for generating test data
def valid_base62_code_strategy(min_len=4, max_len=10):
    """Generate valid Base62 short codes within length bounds."""
    return st.text(
        alphabet=BASE62_CHARS,
        min_size=min_len,
        max_size=max_len
    ).filter(lambda x: len(x) >= min_len)


def invalid_length_code_strategy():
    """Generate codes with invalid length (too short or too long)."""
    return st.one_of(
        # Too short (1-3 characters)
        st.text(alphabet=BASE62_CHARS, min_size=1, max_size=3),
        # Too long (11+ characters)
        st.text(alphabet=BASE62_CHARS, min_size=11, max_size=20),
    )


def invalid_chars_code_strategy():
    """Generate codes with invalid characters (non-Base62)."""
    invalid_chars = '!@#$%^&*()_+-=[]{}|;:\'",.<>?/\\`~ '
    return st.text(
        alphabet=invalid_chars,
        min_size=4,
        max_size=10
    ).filter(lambda x: len(x) >= 4)


def mixed_invalid_code_strategy():
    """Generate codes with mix of valid and invalid characters."""
    return st.builds(
        lambda valid, invalid: valid[:2] + invalid + valid[2:],
        st.text(alphabet=BASE62_CHARS, min_size=4, max_size=6),
        st.text(alphabet='!@#$%^&*', min_size=1, max_size=2)
    ).filter(lambda x: 4 <= len(x) <= 10)


@pytest.mark.django_db
class TestShortCodeFormatValidation:
    """
    Property 9: Short Code Format Validation
    
    For any short code that doesn't conform to Base62 format or has length
    outside 4-10 characters, the creation request should be rejected.
    
    Validates: Requirements 2.6
    """

    @settings(max_examples=100, deadline=None)
    @given(code=valid_base62_code_strategy())
    def test_valid_base62_codes_accepted(self, code):
        """
        Feature: url-shortener, Property 9: 短码格式验证
        Validates: Requirements 2.6
        
        For any valid Base62 code (4-10 characters, a-z A-Z 0-9 only),
        validation should pass.
        """
        generator = ShortCodeGenerator()
        
        # Valid codes should pass validation
        assert generator.validate(code), \
            f"Valid code '{code}' should pass validation"

    @settings(max_examples=100, deadline=None)
    @given(code=invalid_length_code_strategy())
    def test_invalid_length_codes_rejected(self, code):
        """
        Feature: url-shortener, Property 9: 短码格式验证
        Validates: Requirements 2.6
        
        For any code with length outside 4-10 characters,
        validation should fail.
        """
        generator = ShortCodeGenerator()
        
        # Invalid length codes should fail validation
        assert not generator.validate(code), \
            f"Code '{code}' with length {len(code)} should fail validation"

    @settings(max_examples=100, deadline=None)
    @given(code=invalid_chars_code_strategy())
    def test_invalid_chars_codes_rejected(self, code):
        """
        Feature: url-shortener, Property 9: 短码格式验证
        Validates: Requirements 2.6
        
        For any code containing non-Base62 characters,
        validation should fail.
        """
        generator = ShortCodeGenerator()
        
        # Codes with invalid characters should fail validation
        assert not generator.validate(code), \
            f"Code '{code}' with invalid characters should fail validation"

    @settings(max_examples=100, deadline=None)
    @given(code=mixed_invalid_code_strategy())
    def test_mixed_invalid_codes_rejected(self, code):
        """
        Feature: url-shortener, Property 9: 短码格式验证
        Validates: Requirements 2.6
        
        For any code containing a mix of valid and invalid characters,
        validation should fail.
        """
        generator = ShortCodeGenerator()
        
        # Mixed codes should fail validation
        assert not generator.validate(code), \
            f"Code '{code}' with mixed characters should fail validation"

    @settings(max_examples=100, deadline=None)
    @given(st.data())
    def test_generated_codes_always_valid(self, data):
        """
        Feature: url-shortener, Property 9: 短码格式验证
        Validates: Requirements 2.6
        
        For any generated short code, it should always pass validation.
        """
        generator = ShortCodeGenerator()
        
        # Generate a code with random valid length
        length = data.draw(st.integers(min_value=4, max_value=10))
        code = generator.generate(length)
        
        # Generated codes should always be valid
        assert generator.validate(code), \
            f"Generated code '{code}' should pass validation"
        
        # Verify length is correct
        assert len(code) == length, \
            f"Generated code length {len(code)} should equal requested length {length}"
        
        # Verify all characters are Base62
        for char in code:
            assert char in BASE62_CHARS, \
                f"Character '{char}' in generated code should be Base62"

    def test_empty_code_rejected(self):
        """
        Feature: url-shortener, Property 9: 短码格式验证
        Validates: Requirements 2.6
        
        Empty string should fail validation.
        """
        generator = ShortCodeGenerator()
        
        assert not generator.validate(''), "Empty code should fail validation"
        assert not generator.validate(None), "None should fail validation"

    @settings(max_examples=100, deadline=None)
    @given(
        code=st.text(
            alphabet=BASE62_CHARS + ' \t\n',
            min_size=4,
            max_size=10
        ).filter(lambda x: any(c in ' \t\n' for c in x))
    )
    def test_whitespace_codes_rejected(self, code):
        """
        Feature: url-shortener, Property 9: 短码格式验证
        Validates: Requirements 2.6
        
        For any code containing whitespace, validation should fail.
        """
        generator = ShortCodeGenerator()
        
        # Codes with whitespace should fail validation
        assert not generator.validate(code), \
            f"Code '{repr(code)}' with whitespace should fail validation"
